"""打包後的程式入口（PyInstaller）。

啟動失敗時（檔案壞了、更新沒裝完整等）不彈英文的 "Unhandled exception"，改成中文提示，
引導去官網下載安裝包覆蓋安裝；錯誤寫進 crash.log 方便排查。這裡儘量少依賴程式本身，程式壞了也能彈出來。
"""

import os
import sys
import time
import traceback

DOWNLOAD_PAGE = "https://aramhex.com/#download"


def _crash_log(text: str) -> str:
    base = os.environ.get("ARAMHEX_HOME") or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AramHexTW")
    if os.path.isfile(os.path.join(os.path.dirname(sys.executable), "portable.txt")):
        base = os.path.join(os.path.dirname(sys.executable), "userdata")
    try:
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "crash.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n{text}\n")
        return path
    except OSError:
        return ""


def _crash(text: str) -> None:
    path = _crash_log(text)
    msg = ("海克斯大亂鬥助手打不開了。\n\n"
           "請到官網下載安裝包，直接覆蓋安裝就行（設定會保留）。\n\n"
           "點「是」開啟官網下載頁。")
    if path:
        msg += f"\n\n錯誤記錄：{path}"
    try:
        import ctypes
        if ctypes.windll.user32.MessageBoxW(None, msg, "海克斯大亂鬥助手", 0x4 | 0x10) == 6:  # 是/否 + 錯誤圖示；6 = 是
            import webbrowser
            webbrowser.open(DOWNLOAD_PAGE)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from lolhex.__main__ import main
        code = main()
    except SystemExit:
        raise
    except BaseException:
        _crash(traceback.format_exc())
        code = 1
    sys.exit(code)
