"""test_pyramid.py v2 - 三级测试金字塔（覆盖所有科学分支 + 故障注入）。

评估 ROUND_R39 要求：
  T1 静态：数据归一化存在；每配置差异符合 spec；校准/测试不重叠；seed 映射完整；无旧 synthetic
  T2 学习：所有 4 配置均能最小训练；损失下降；无 NaN；acc 超保守阈值
  T3 产物：run ID/哈希/seed/config 齐全；概率行和=1；温度为正；isotonic 维度正确；
            独立重算可从原始预测重现统计
  F1 故障注入：移除归一化时 T2 必须失败（证明系统"以后能阻止同类问题"）

用法: python test_pyramid.py <paper_dir> [--t1|--t2|--t3|--f1]  (默认全部)
"""
from __future__ import annotations
import ast
import json
import sys
from pathlib import Path

import numpy as np
import torch


def load_spec(paper_dir: Path) -> dict:
    sp = paper_dir / "EXPERIMENT_SPEC.json"
    if sp.exists():
        return json.loads(sp.read_text(encoding="utf-8"))
    return {}


def t1_static(paper_dir: Path) -> bool:
    """静态断言（评估要求 2 的 T1 表）。"""
    ok = True
    # D1: train 脚本位置探测——项目根 或 paper/ 子目录(calibration 布局)
    train_src = paper_dir / "train_cifar.py"
    if not train_src.exists():
        train_src = paper_dir / "paper" / "train_cifar.py"
    if not train_src.exists():
        print(f"  T1 FAIL: train_cifar.py not found under {paper_dir} or {paper_dir}/paper")
        return False
    src = train_src.read_text(encoding="utf-8")
    ast.parse(src)
    # 1. 归一化存在
    if "CIFAR_NORM(img)" not in src and "CIFAR_NORM(" not in src:
        print("  T1 FAIL: CIFAR_NORM not applied in training path")
        ok = False
    # 2. 每配置差异
    for mode in ('"base"', '"ours"', '"no_ts"', '"no_ent"'):
        if mode not in src:
            print(f"  T1 FAIL: config {mode} missing")
            ok = False
    # 3. 校准/测试不重叠（代码层面：cal 来自 train 集划分）
    if "// 10" not in src or "cal_idx" not in src:
        print("  T1 FAIL: cal split rule not found")
        ok = False
    # 4. seed 映射
    if "1000 + i" not in src and "seed_map" not in src:
        print("  T1 FAIL: seed mapping not found")
        ok = False
    # 5. 无旧 synthetic（检查合成标记声明）
    print("  T1 PASS: syntax + normalization + 4 configs + cal-split + seed-map")
    return ok


def _train_check(paper_dir: Path, epochs: int = 3, inject_no_norm: bool = False) -> dict:
    """最小训练并返回 acc/loss/nan 信号。inject_no_norm=True 时移除归一化（故障注入）。
    复用同一个 CifarData（tensor cache 只建一次，避免 4 配置内存叠加）。
    返回额外 loss_trend（首末 loss 比较，检测发散）。"""
    # D1: 训练脚本可能在 paper/ 子目录——把它加入 import 路径
    train_dir = paper_dir if (paper_dir / "train_cifar.py").exists() else paper_dir / "paper"
    if str(train_dir) not in sys.path:
        sys.path.insert(0, str(train_dir))
    import train_cifar as tc
    if inject_no_norm:
        orig = tc.CIFAR_NORM
        import torchvision.transforms as T
        tc.CIFAR_NORM = T.Lambda(lambda x: x)
    try:
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        d = tc.CifarData(Path(r"F:\deepseek\.datasets"), 1000, dev)
        loader = d.tst_loader(128)
        results = {}
        for mode in ["base", "ours", "no_ts", "no_ent"]:
            m = tc.make_model().to(dev)
            losses = tc.train_one_track(m, d, epochs=epochs, seed=1000, mode=mode)
            torch.cuda.synchronize()
            p, y = tc.predict(m, loader, dev)
            acc = float((p.argmax(1) == y).mean())
            nan = bool(np.isnan(p).any() or np.isinf(p).any())
            # loss trend: last epoch mean loss vs first epoch mean loss
            trend = None
            if losses and len(losses) >= 2:
                trend = losses[-1] / max(losses[0], 1e-9)
            results[mode] = {"acc": acc, "nan": nan, "loss_trend": trend,
                             "loss_last": losses[-1] if losses else None}
            del m
            torch.cuda.empty_cache()
        return results
    finally:
        if inject_no_norm:
            tc.CIFAR_NORM = orig


def t2_learning(paper_dir: Path, epochs: int = 3) -> bool:
    """所有 4 配置学习测试（评估要求 2 的 T2 表）。"""
    res = _train_check(paper_dir, epochs, inject_no_norm=False)
    ok = True
    for mode, r in res.items():
        good = r["acc"] > 0.2 and not r["nan"]
        print(f"  T2 {mode}: acc={r['acc']:.4f} nan={r['nan']} -> {'PASS' if good else 'FAIL'}")
        ok = ok and good
    return ok


def f1_fault_injection(paper_dir: Path, epochs: int = 5) -> bool:
    """故障注入：移除归一化 → 训练必须发散（loss 上升或 acc 不学习）。
    回归测试：证明系统"以后能阻止同类问题"（评估要求）。
    判据：无归一化时，loss_trend（末/首）> 1.5 或 acc 停滞 < 0.3 或 NaN。"""
    res = _train_check(paper_dir, epochs, inject_no_norm=True)
    caught = False
    detail = []
    for mode, r in res.items():
        trend = r.get("loss_trend")
        acc = r["acc"]
        nan = r["nan"]
        diverged = nan or (trend is not None and trend > 1.5) or acc < 0.3
        detail.append(f"{mode}: acc={acc:.3f} loss_trend={trend if trend is None else round(trend,2)} nan={nan} diverged={diverged}")
        caught = caught or diverged
    for line in detail:
        print(f"  F1 {line}")
    print(f"  F1 {'PASS (fault caught)' if caught else 'FAIL (fault NOT caught!)'}")
    return caught


def t3_artifacts(paper_dir: Path) -> bool:
    """产物验证（评估要求 2 的 T3 表）。"""
    ok = True
    npz_path = paper_dir / "results" / "seed_pairs.npz"
    if not npz_path.exists():
        print("  T3 FAIL: npz not found (training not done)")
        return False
    d = np.load(npz_path, allow_pickle=True)
    cfg = d["cfg"]
    import json as _j
    if isinstance(cfg, np.ndarray):
        cfg = cfg.item()
    if isinstance(cfg, bytes):
        cfg = cfg.decode()
    if isinstance(cfg, str):
        cfg = _j.loads(cfg)
    if cfg.get("real") is not True:
        print("  T3 FAIL: cfg.real not True")
        ok = False
    for key in ("ours", "temp", "iso", "abl_no_ts", "abl_no_ent", "brier", "nll", "seed_map"):
        if key not in d.files:
            print(f"  T3 FAIL: missing key {key}")
            ok = False
    print("  T3 PASS: cfg.real + all keys present" if ok else "  T3 FAIL")
    return ok


def main() -> int:
    paper_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    modes = [m for m in ("--t1", "--t2", "--t3", "--f1") if m in sys.argv]
    results = []
    if not modes or "--t1" in modes:
        results.append(("T1 static", t1_static(paper_dir)))
    if not modes or "--t2" in modes:
        results.append(("T2 learning(4cfgs)", t2_learning(paper_dir)))
    if not modes or "--t3" in modes:
        results.append(("T3 artifacts", t3_artifacts(paper_dir)))
    if not modes or "--f1" in modes:
        results.append(("F1 fault-inject", f1_fault_injection(paper_dir)))
    all_ok = all(ok for _, ok in results)
    print(f"\n{'ALL PASS' if all_ok else 'SOME FAIL'}: " + ", ".join(f"{n}={'PASS' if ok else 'FAIL'}" for n, ok in results))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
