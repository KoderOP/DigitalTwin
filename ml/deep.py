"""Multimodal deep fusion model (PyTorch).

Architecture
------------
    wearable sequence (6 h x 5 min x C, avg-pooled to 10 min) --GRU--> h_1..h_T --+
                                                            |  cross-attention: EHR embedding is the
    static EHR vector --MLP--> e  --------------------------+  query over GRU states -> context c
    wearable summary + clock --MLP--> s

    temporal  = LayerNorm(h_T + c + s)
    gate      = sigmoid(W [temporal ; e])
    fused     = gate * temporal + (1 - gate) * e
    trunk     = MLP([fused ; temporal ; e]) -> heads
        spike logit (P(glucose > 180 within 120 min))
        hypo logit  (P(glucose < 70 within 120 min))
        quantiles   (P10/P50/P90 of glucose change at +30/60/90/120 min, in units of 50 mg/dL)

Ablations reuse the same class: ``wearable_only`` drops the EHR branch (learned query, no gate);
``ehr_only`` drops the sequence and wearable summary (clock features are kept as context).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score
from torch import nn

from common import get_logger

log = get_logger("ml.deep")
G_SCALE = 50.0


def _mlp(i: int, o: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(nn.Linear(i, o), nn.GELU(), nn.Dropout(dropout), nn.Linear(o, o), nn.GELU())


class CausalTCN(nn.Module):
    """Dilated causal temporal convolution network (residual blocks). Output (B, T, d).

    With kernel 3 and dilations 1..16 the receptive field is 63 steps (5.25 h). Convolutions run in
    parallel over time, so it is several times faster than a GRU on CPU.
    """

    def __init__(self, n_in: int, d: int, dilations: tuple[int, ...] = (1, 2, 4, 8, 16), k: int = 3, dropout: float = 0.1) -> None:
        super().__init__()
        self.inp = nn.Conv1d(n_in, d, 1)
        self.convs = nn.ModuleList([nn.Conv1d(d, d, k, dilation=dl) for dl in dilations])
        self.pads = [(k - 1) * dl for dl in dilations]
        self.drop = nn.Dropout(dropout)
        self.input_size = n_in

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.inp(x.transpose(1, 2))
        for conv, pad in zip(self.convs, self.pads):
            h = h + self.drop(nn.functional.gelu(conv(nn.functional.pad(h, (pad, 0)))))
        return h.transpose(1, 2)


class FusionNet(nn.Module):
    def __init__(self, mode: str, n_seq: int, n_tab: int, n_static: int, hidden: int = 64,
                 static_hidden: int = 64, dropout: float = 0.15, n_h: int = 4, n_q: int = 3,
                 encoder: str = "gru", pool: int = 1) -> None:
        super().__init__()
        assert mode in ("fused", "wearable_only", "ehr_only")
        assert encoder in ("tcn", "gru")
        self.mode, self.n_h, self.n_q, self.encoder, self.pool = mode, n_h, n_q, encoder, pool
        self.use_seq = mode != "ehr_only"
        self.use_static = mode != "wearable_only"
        d = hidden
        if self.use_seq:
            self.gru = nn.GRU(n_seq, d, batch_first=True) if encoder == "gru" else CausalTCN(n_seq, d, dropout=dropout)
            self.attn = nn.MultiheadAttention(d, num_heads=4, batch_first=True)
            self.q_learned = nn.Parameter(torch.zeros(1, 1, d))
            self.norm = nn.LayerNorm(d)
        self.tab = _mlp(n_tab, d, dropout)
        if self.use_static:
            self.static = _mlp(n_static, static_hidden, dropout)
            self.s2q = nn.Linear(static_hidden, d)
            self.s2d = nn.Linear(static_hidden, d)
        if self.use_seq and self.use_static:
            self.gate = nn.Linear(2 * d, d)
        trunk_in = 3 * d if (self.use_seq and self.use_static) else 2 * d
        self.trunk = nn.Sequential(nn.Linear(trunk_in, d), nn.GELU(), nn.Dropout(dropout), nn.Linear(d, d), nn.GELU())
        self.head_spike = nn.Linear(d, 1)
        self.head_hypo = nn.Linear(d, 1)
        self.head_q = nn.Linear(d, n_h * n_q)

    def forward(self, seq: torch.Tensor | None, tab: torch.Tensor, static: torch.Tensor | None) -> dict[str, torch.Tensor]:
        s = self.tab(tab)
        emb = self.static(static) if self.use_static else None
        e = self.s2d(emb) if emb is not None else None
        if self.use_seq:
            if self.pool > 1:  # average-pool time (e.g. 5-min -> 10-min steps) to cut CPU cost
                B, T, C = seq.shape
                seq = seq[:, T % self.pool :].reshape(B, T // self.pool, self.pool, C).mean(2)
            H = self.gru(seq)[0] if self.encoder == "gru" else self.gru(seq)
            q =self.s2q(emb).unsqueeze(1) if emb is not None else self.q_learned.expand(len(seq), 1, -1)
            ctx, attn_w = self.attn(q, H, H, need_weights=True)
            temporal = self.norm(H[:, -1] + ctx.squeeze(1) + s)
            if self.use_static:
                g = torch.sigmoid(self.gate(torch.cat([temporal, e], dim=1)))
                fused = g * temporal + (1 - g) * e
                z = torch.cat([fused, temporal, e], dim=1)
            else:
                g = None
                z = torch.cat([temporal, s], dim=1)
        else:
            attn_w, g = None, None
            z = torch.cat([e, s], dim=1)
        h = self.trunk(z)
        q = self.head_q(h).view(-1, self.n_h, self.n_q)
        q = torch.cat([q[..., :1], q[..., :1] + torch.cumsum(nn.functional.softplus(q[..., 1:]), dim=-1)], dim=-1)  # monotone quantiles
        return {"spike": self.head_spike(h).squeeze(1), "hypo": self.head_hypo(h).squeeze(1), "q": q,
                "attn": attn_w, "gate": g}


def pinball(pred: torch.Tensor, target: torch.Tensor, quantiles: torch.Tensor) -> torch.Tensor:
    """Masked pinball loss; ``target`` (B, H) may contain NaN."""
    mask = ~torch.isnan(target)
    t = torch.nan_to_num(target).unsqueeze(-1)
    diff = t - pred
    loss = torch.maximum(quantiles * diff, (quantiles - 1) * diff)
    loss = loss * mask.unsqueeze(-1)
    return loss.sum() / mask.sum().clamp(min=1) / len(quantiles)


@dataclass
class DeepBundle:
    """A trained model plus everything needed to reproduce its inputs at serving time."""

    model: FusionNet
    mode: str
    tab_cols: list[str]
    static_cols: list[str]
    tab_mean: np.ndarray
    tab_std: np.ndarray
    static_mean: np.ndarray
    static_std: np.ndarray
    seq_mean: np.ndarray
    window: int
    quantiles: list[float]
    horizons: list[int]
    calibrator: IsotonicRegression | None = None

    def prep(self, tab: np.ndarray, static: np.ndarray | None) -> tuple[np.ndarray, np.ndarray | None]:
        t = np.nan_to_num((tab - self.tab_mean) / self.tab_std).astype(np.float32)
        s = None
        if static is not None and self.static_cols:
            s = np.nan_to_num((static - self.static_mean) / self.static_std).astype(np.float32)
        return t, s

    @torch.no_grad()
    def predict(self, seq: np.ndarray | None, tab: np.ndarray, static: np.ndarray | None, batch: int = 2048) -> dict[str, np.ndarray]:
        """Calibrated spike probability, hypo probability and glucose-change quantiles (mg/dL)."""
        self.model.eval()
        t, s = self.prep(tab, static)
        outs: dict[str, list[np.ndarray]] = {"spike_raw": [], "hypo": [], "q": []}
        for i in range(0, len(t), batch):
            sq = torch.from_numpy(seq[i : i + batch]) if (seq is not None and self.model.use_seq) else None
            ss = torch.from_numpy(s[i : i + batch]) if s is not None else None
            o = self.model(sq, torch.from_numpy(t[i : i + batch]), ss)
            outs["spike_raw"].append(torch.sigmoid(o["spike"]).numpy())
            outs["hypo"].append(torch.sigmoid(o["hypo"]).numpy())
            outs["q"].append(o["q"].numpy() * G_SCALE)
        res = {k: np.concatenate(v) for k, v in outs.items()}
        res["spike"] = self.calibrator.predict(res["spike_raw"]) if self.calibrator is not None else res["spike_raw"]
        return res

    def save(self, path: Path) -> None:
        torch.save({"state": self.model.state_dict(), "init": self.model_init(), **{k: v for k, v in self.__dict__.items() if k != "model"}}, path)

    def model_init(self) -> dict:
        m = self.model
        return {"mode": m.mode, "n_seq": m.gru.input_size if m.use_seq else 1, "n_tab": m.tab[0].in_features,
                "n_static": m.static[0].in_features if m.use_static else 1, "hidden": m.head_spike.in_features,
                "static_hidden": m.static[0].out_features if m.use_static else 64, "n_h": m.n_h, "n_q": m.n_q,
                "encoder": m.encoder, "pool": m.pool}

    @staticmethod
    def load(path: Path) -> "DeepBundle":
        ck = torch.load(path, map_location="cpu", weights_only=False)
        model = FusionNet(**ck.pop("init"))
        model.load_state_dict(ck.pop("state"))
        model.eval()
        return DeepBundle(model=model, **ck)


def train_deep(mode: str, data: dict, cfg: dict, seed: int, epochs: int) -> tuple[DeepBundle, dict]:
    """Train one variant.

    ``data`` holds ``train`` / ``val`` dicts with numpy arrays: ``seq`` (B,T,C) or a callable that
    returns windows for given positions, ``tab``, ``static``, ``y`` (spike), ``yh`` (hypo), ``dg`` (B,4)
    glucose change targets, plus column metadata.
    """
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(cfg["torch_threads"])
    tr, va = data["train"], data["val"]
    tab_mean = np.nanmean(tr["tab"], axis=0)
    tab_std = np.nan_to_num(np.nanstd(tr["tab"], axis=0), nan=1.0) + 1e-6
    tab_mean = np.nan_to_num(tab_mean)
    if tr["static"] is not None:
        st_mean = tr["static"].mean(axis=0)
        st_std = tr["static"].std(axis=0) + 1e-6
    else:
        st_mean = st_std = np.zeros(0)
    model = FusionNet(mode, n_seq=data["n_seq"], n_tab=tr["tab"].shape[1],
                      n_static=tr["static"].shape[1] if tr["static"] is not None else 1,
                      hidden=cfg["hidden"], static_hidden=cfg["static_hidden"], dropout=cfg["dropout"],
                      n_h=len(cfg["horizons_min"]), n_q=len(cfg["quantiles"]), encoder=cfg.get("encoder", "gru"),
                      pool=cfg.get("pool", 1))
    bundle = DeepBundle(model, mode, data["tab_cols"], data["static_cols"], tab_mean, tab_std, st_mean, st_std,
                        data["seq_mean"], data["window"], list(cfg["quantiles"]), list(cfg["horizons_min"]))
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    qs = torch.tensor(cfg["quantiles"], dtype=torch.float32)
    bce = nn.BCEWithLogitsLoss()

    t_tab, t_st = bundle.prep(tr["tab"], tr["static"])
    v_tab, v_st = bundle.prep(va["tab"], va["static"])
    n = len(t_tab)
    log.info("Deep[%s] %d train / %d val samples, %d params", mode, n, len(v_tab), sum(p.numel() for p in model.parameters()))
    best, best_state, bad, hist = -1.0, None, 0, []
    for ep in range(epochs):
        model.train()
        t0 = time.time()
        perm = np.random.permutation(n)
        tot = 0.0
        for i in range(0, n, cfg["batch_size"]):
            b = perm[i : i + cfg["batch_size"]]
            seq = torch.from_numpy(tr["seq"](b)) if model.use_seq else None
            st = torch.from_numpy(t_st[b]) if t_st is not None else None
            o = model(seq, torch.from_numpy(t_tab[b]), st)
            dg = torch.from_numpy(tr["dg"][b] / G_SCALE)
            loss = (bce(o["spike"], torch.from_numpy(tr["y"][b])) + 0.2 * bce(o["hypo"], torch.from_numpy(tr["yh"][b]))
                    + 0.5 * pinball(o["q"], dg, qs))
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(b)
        sched.step()
        pv = _predict_raw(model, va, v_tab, v_st)
        ap = average_precision_score(va["y"], pv)
        hist.append({"epoch": ep + 1, "train_loss": tot / n, "val_pr_auc": float(ap), "sec": time.time() - t0})
        log.info("Deep[%s] epoch %d loss %.4f val PR-AUC %.4f (%.0fs)", mode, ep + 1, tot / n, ap, time.time() - t0)
        if ap > best + 1e-4:
            best, bad = ap, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= cfg["patience"]:
                break
    model.load_state_dict(best_state)
    raw = _predict_raw(model, va, v_tab, v_st)
    bundle.calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, va["y"])
    return bundle, {"history": hist, "best_val_pr_auc": float(best)}


@torch.no_grad()
def _predict_raw(model: FusionNet, d: dict, tab: np.ndarray, st: np.ndarray | None, batch: int = 4096) -> np.ndarray:
    model.eval()
    out = []
    for i in range(0, len(tab), batch):
        b = np.arange(i, min(i + batch, len(tab)))
        seq = torch.from_numpy(d["seq"](b)) if model.use_seq else None
        s = torch.from_numpy(st[b]) if st is not None else None
        out.append(torch.sigmoid(model(seq, torch.from_numpy(tab[b]), s)["spike"]).numpy())
    return np.concatenate(out)
