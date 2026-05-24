"""Python 版本的 loop runner，繞過 PowerShell ExecutionPolicy 限制。

用法：
    python -m scripts.run_loop                # 每 600 秒 (10 min) 跑一次
    python -m scripts.run_loop 900            # 每 900 秒 (15 min) 跑一次

Ctrl+C 中止。
"""
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 600
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
