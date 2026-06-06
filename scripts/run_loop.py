"""Python 版本的 loop runner（VPS 常駐 / 本機測試均適用）。

用法：
    python -m scripts.run_loop        # 預設 60 秒（VPS 1 分鐘模式）
    python -m scripts.run_loop 300    # 每 5 分鐘

VPS 部署：由 systemd 管理（deploy/polymarket-bot.service）
Ctrl+C 中止。
"""
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60  # VPS 預設 1 分鐘
    project_dir = Path(__file__).resolve().parent.parent
    print(f"Loop runner 啟動，每 {interval} 秒跑一次 pipeline")
    print(f"工作目錄: {project_dir}")
    print("Ctrl+C 中止\n")

    try:
        while True:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] ── tick ──")
            try:
                subprocess.run(
                    [sys.executable, "-m", "scripts.run_pipeline"],
                    cwd=project_dir,
                    check=False,
                )
            except Exception as e:
                print(f"Pipeline 跑錯: {e}")
            print(f"sleep {interval}s...\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n中止")


if __name__ == "__main__":
    main()
