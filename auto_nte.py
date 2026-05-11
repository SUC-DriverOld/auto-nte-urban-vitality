from __future__ import annotations

import logging
import sys
import time
from ctypes import POINTER, Structure, WINFUNCTYPE, WinDLL, byref, c_bool, c_int, c_uint, create_unicode_buffer
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

import pyautogui
import psutil


CLICK_HOLD_SECONDS = 0.2
CLICK_INTERVAL_SECONDS = 0.5
CONTINUOUS_CLICK_COUNT = 55
START_DELAY_SECONDS = 10
BASE_CLIENT_WIDTH = 1920
BASE_CLIENT_HEIGHT = 1080


logger = logging.getLogger("auto_nte")
PROCESS_NAME = "HTGame.exe"


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Size:
    width: int
    height: int


class GUITHREADINFO(Structure):
    _fields_ = [
        ("cbSize", c_int),
        ("flags", c_uint),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


FIRST_CLICK_POINT = Point(1710, 1000)
CONTINUOUS_CLICK_POINT = Point(86, 444)
EXIT_CLICK_POINT = Point(42, 42)
FINAL_CLICK_POINT = Point(1166, 840)


user32 = WinDLL("user32", use_last_error=True)
kernel32 = WinDLL("kernel32", use_last_error=True)

EnumWindowsProc = WINFUNCTYPE(c_bool, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = c_bool
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = c_bool
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, c_int]
user32.GetWindowTextW.restype = c_int
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = c_bool
user32.ClientToScreen.argtypes = [wintypes.HWND, POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = c_bool
user32.GetClientRect.argtypes = [wintypes.HWND, POINTER(wintypes.RECT)]
user32.GetClientRect.restype = c_bool


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def get_process_ids_by_name(process_name: str) -> list[int]:
    process_ids: list[int] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] == process_name:
                process_ids.append(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return process_ids


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_window_origin(hwnd: int) -> Point:
    client_origin = wintypes.POINT(0, 0)
    success = user32.ClientToScreen(hwnd, byref(client_origin))
    if not success:
        raise RuntimeError("无法读取游戏窗口位置。")
    return Point(client_origin.x, client_origin.y)


def get_client_size(hwnd: int) -> Size:
    rect = wintypes.RECT()
    success = user32.GetClientRect(hwnd, byref(rect))
    if not success:
        raise RuntimeError("无法读取游戏客户区尺寸。")
    return Size(rect.right - rect.left, rect.bottom - rect.top)


def find_main_window_for_pids(process_ids: list[int]) -> int | None:
    pid_set = set(process_ids)
    matched_hwnd: int | None = None

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        nonlocal matched_hwnd
        if not user32.IsWindowVisible(hwnd):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, byref(pid))
        if pid.value not in pid_set:
            return True

        title = get_window_text(hwnd)
        if not title.strip():
            return True

        matched_hwnd = hwnd
        return False

    user32.EnumWindows(callback, 0)
    return matched_hwnd


def activate_game_window() -> tuple[int, Point, Size]:
    logger.info("检查游戏进程 %s 是否存在。", PROCESS_NAME)
    process_ids = get_process_ids_by_name(PROCESS_NAME)
    if not process_ids:
        raise RuntimeError(f"未找到游戏进程 {PROCESS_NAME}。请先启动游戏。")

    logger.info("已找到游戏进程 PID：%s", ", ".join(str(pid) for pid in process_ids))
    hwnd = find_main_window_for_pids(process_ids)
    if hwnd is None:
        raise RuntimeError(f"已找到进程 {PROCESS_NAME}，但未找到可见主窗口。")

    window_title = get_window_text(hwnd) or "<无标题>"
    logger.info("定位到游戏窗口句柄 %s，标题：%s", hwnd, window_title)
    window_origin = get_window_origin(hwnd)
    client_size = get_client_size(hwnd)
    logger.info("游戏客户区左上角坐标：(%d, %d)", window_origin.x, window_origin.y)
    logger.info("游戏客户区尺寸：%d x %d", client_size.width, client_size.height)
    return hwnd, window_origin, client_size


def prompt_total_loops(input_fn: Callable[[str], str] = input) -> int:
    while True:
        raw = input_fn("请输入要执行的大循环次数：").strip()
        if not raw:
            print("输入不能为空，请重新输入。")
            continue
        try:
            loops = int(raw)
        except ValueError:
            print("请输入正整数。")
            continue
        if loops <= 0:
            print("请输入大于 0 的整数。")
            continue
        return loops


def sleep_with_log(seconds: float, reason: str) -> None:
    logger.info("等待 %.1f 秒：%s", seconds, reason)
    time.sleep(seconds)


def countdown(seconds: int, reason: str) -> None:
    logger.info("%s，倒计时 %d 秒后开始。", reason, seconds)
    for remaining in range(seconds, 0, -1):
        logger.info("剩余 %d 秒...", remaining)
        time.sleep(1)


def move_to(point: Point) -> None:
    logger.info("移动鼠标到 (%d, %d)", point.x, point.y)
    pyautogui.moveTo(point.x, point.y)


def scale_relative_point(relative_point: Point, client_size: Size) -> Point:
    scaled_point = Point(
        round(relative_point.x * client_size.width / BASE_CLIENT_WIDTH),
        round(relative_point.y * client_size.height / BASE_CLIENT_HEIGHT),
    )
    logger.info(
        "基准坐标 (%d, %d) 按客户区尺寸 %d x %d 缩放为 (%d, %d)",
        relative_point.x,
        relative_point.y,
        client_size.width,
        client_size.height,
        scaled_point.x,
        scaled_point.y,
    )
    return scaled_point


def resolve_screen_point(window_origin: Point, client_size: Size, relative_point: Point) -> Point:
    scaled_point = scale_relative_point(relative_point, client_size)
    screen_point = Point(window_origin.x + scaled_point.x, window_origin.y + scaled_point.y)
    logger.info(
        "缩放后相对坐标 (%d, %d) 换算为屏幕坐标 (%d, %d)",
        scaled_point.x,
        scaled_point.y,
        screen_point.x,
        screen_point.y,
    )
    return screen_point


def click(button: str = "left") -> None:
    logger.info("%s键点击一次：按下 %.1f 秒后抬起", "左" if button == "left" else "右", CLICK_HOLD_SECONDS)
    pyautogui.mouseDown(button=button)
    time.sleep(CLICK_HOLD_SECONDS)
    pyautogui.mouseUp(button=button)


def press_key(key: str) -> None:
    logger.info("按键 %s 一次：按下 %.1f 秒后抬起", key.upper(), CLICK_HOLD_SECONDS)
    pyautogui.keyDown(key)
    time.sleep(CLICK_HOLD_SECONDS)
    pyautogui.keyUp(key)


def continuous_left_click(total_clicks: int, interval_seconds: float) -> None:
    logger.info(
        "开始连续左键点击：目标点击 %d 次，单次间隔 %.1f 秒",
        total_clicks,
        interval_seconds,
    )
    for click_count in range(1, total_clicks + 1):
        logger.info("连续点击第 %d/%d 次", click_count, total_clicks)
        click("left")
        if click_count < total_clicks:
            sleep_for = interval_seconds - CLICK_HOLD_SECONDS
            if sleep_for > 0:
                time.sleep(sleep_for)

    logger.info("连续点击结束，实际完成 %d 次。", total_clicks)


def run_single_loop(loop_index: int, total_loops: int, window_origin: Point, client_size: Size) -> None:
    logger.info("========== 开始第 %d/%d 轮 ==========", loop_index, total_loops)
    sleep_with_log(2, "流程开始前等待")
    press_key("f")
    sleep_with_log(2, "按下 F 后等待")

    move_to(resolve_screen_point(window_origin, client_size, FIRST_CLICK_POINT))
    click("left")
    sleep_with_log(5, "首次点击后等待")

    move_to(resolve_screen_point(window_origin, client_size, CONTINUOUS_CLICK_POINT))
    continuous_left_click(
        total_clicks=CONTINUOUS_CLICK_COUNT,
        interval_seconds=CLICK_INTERVAL_SECONDS,
    )

    move_to(resolve_screen_point(window_origin, client_size, EXIT_CLICK_POINT))
    click("left")
    sleep_with_log(2, "关闭后等待")

    move_to(resolve_screen_point(window_origin, client_size, FINAL_CLICK_POINT))
    click("left")
    logger.info("========== 第 %d/%d 轮结束 ==========", loop_index, total_loops)


def configure_pyautogui() -> None:
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    logger.info("已关闭 PyAutoGUI failsafe。")


def main() -> int:
    setup_logging()
    configure_pyautogui()

    try:
        total_loops = prompt_total_loops()
        logger.info("用户设置总循环次数：%d", total_loops)
        _hwnd, window_origin, client_size = activate_game_window()
        countdown(START_DELAY_SECONDS, "即将开始自动化流程")

        for loop_index in range(1, total_loops + 1):
            run_single_loop(loop_index, total_loops, window_origin, client_size)

        logger.info("全部流程执行完成，共执行 %d 轮。", total_loops)
        return 0
    except KeyboardInterrupt:
        logger.warning("检测到键盘中断，程序已停止。")
        return 130
    except Exception as exc:  # pragma: no cover
        logger.exception("程序异常退出：%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
