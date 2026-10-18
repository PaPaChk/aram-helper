"""同一個 Windows 使用者只能執行一個助手。

以前只靠本地套接字（QLocalServer）：第二個程序連不上第一個時，就當沒人在跑，自己再起一個。
Windows 上同名管道可以有多個服務端，第一個程序忙、半秒內沒接上連線時就會出現兩個助手。

現在用命名互斥量判斷"有沒有人在跑"，只有一個程序能拿到；套接字只用來通知已有的助手顯示主視窗。
"""

from __future__ import annotations

import ctypes
import sys

WAIT_OBJECT_0, WAIT_ABANDONED = 0x0, 0x80
_held: list = []  # 拿到的互斥量控制代碼：程序退出時由系統釋放


def acquire(name: str, wait_ms: int = 0) -> bool:
    """拿到名為 name 的互斥量返回 True（本程序就是唯一的助手）。等 wait_ms 毫秒還拿不到返回 False。
    非 Windows 或系統呼叫失敗時返回 True：判斷不了就照常啟動，不能讓助手打不開。"""
    if sys.platform != "win32":
        return True
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    k.WaitForSingleObject.restype = ctypes.c_uint32
    k.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    if not _held:
        h = k.CreateMutexW(None, False, "Local\\" + name)
        if not h:
            return True
        _held.append(h)
    # 互斥量歸拿到它的執行緒所有：在主執行緒呼叫，主執行緒一直活到程序結束
    return k.WaitForSingleObject(_held[0], max(0, int(wait_ms))) in (WAIT_OBJECT_0, WAIT_ABANDONED)
