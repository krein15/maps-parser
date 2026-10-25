"""Проверки по расписанию через Планировщик заданий Windows.

Задание описывается целиком в XML (`schtasks /Create /XML`) — короткая форма
schtasks не умеет того, что здесь нужно:
 - рабочая папка задаётся явно, иначе программа не найдёт свои настройки;
 - окно консоли не показывается (pythonw.exe при запуске из исходников);
 - пропущенный запуск (компьютер был выключен) стартует, когда машина вернулась;
 - второй запуск поверх ещё не закончившегося не стартует.

Мониторинг включается по требованию: `schedule on` создаёт и включает задание,
`schedule off` выключает, не стирая настроек.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from xml.sax.saxutils import escape

TASK_FOLDER = "\\Maps Parser\\"
TASK_NAME = "Мониторинг"
TASK_PATH = TASK_FOLDER + TASK_NAME
PROJECT_DIR = Path(__file__).resolve().parents[1]
TIME_LIMIT = "PT4H"  # большая ниша в большом городе собирается долго
NEVER_RAN = 267011  # SCHED_S_TASK_HAS_NOT_RUN

Runner = Callable[..., subprocess.CompletedProcess]


class SchedulerError(RuntimeError):
    """Беда с Планировщиком. Текст можно показывать пользователю как есть."""


@dataclass(frozen=True)
class TaskStatus:
    exists: bool
    enabled: bool = False
    next_run: str = ""
    last_run: str = ""
    last_result: str = ""


def launcher() -> tuple[Path, list[str], Path]:
    """Что запускает задание: собранная программа или pythonw с пакетом из папки проекта."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        return executable, [], executable.parent
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    return (windowless if windowless.exists() else python), ["-m", "mapsparser"], PROJECT_DIR


def task_xml(
    at: time,
    *,
    days: int = 1,
    now: datetime | None = None,
    program: tuple[Path, list[str], Path] | None = None,
) -> str:
    """Описание задания: раз в `days` суток в указанное время по местному времени."""
    command, prefix, workdir = program or launcher()
    arguments = " ".join([*prefix, "monitor"])
    moment = now or datetime.now()
    start = datetime.combine(moment.date(), at)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Карты Парсер: новые фирмы в ваших нишах, уведомления в Telegram. \
Проверка в {at:%H:%M}, раз в {days} сут.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start:%Y-%m-%dT%H:%M:%S}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>{days}</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>{TIME_LIMIT}</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(command))}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _run(runner: Runner, arguments: list[str]) -> subprocess.CompletedProcess:
    try:
        return runner(
            ["schtasks", *arguments],
            capture_output=True,
            text=True,
            encoding="cp866",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:  # не Windows
        raise SchedulerError("Планировщик заданий есть только в Windows") from exc


def create(at: time, *, days: int = 1, runner: Runner | None = None, now: datetime | None = None) -> None:
    """Создаёт или заменяет задание и включает его."""
    runner = runner or subprocess.run
    xml = task_xml(at, days=days, now=now)
    path = Path.home() / f".maps-parser-task-{datetime.now():%H%M%S}.xml"
    path.write_text(xml, encoding="utf-16")
    try:
        done = _run(runner, ["/Create", "/TN", TASK_PATH, "/XML", str(path), "/F"])
        if done.returncode != 0:
            raise SchedulerError(f"Планировщик отказал: {(done.stderr or done.stdout).strip()}")
    finally:
        path.unlink(missing_ok=True)


def enable(*, runner: Runner | None = None) -> None:
    done = _run(runner or subprocess.run, ["/Change", "/TN", TASK_PATH, "/ENABLE"])
    if done.returncode != 0:
        raise SchedulerError(f"Включить не вышло: {(done.stderr or done.stdout).strip()}")


def disable(*, runner: Runner | None = None) -> None:
    done = _run(runner or subprocess.run, ["/Change", "/TN", TASK_PATH, "/DISABLE"])
    if done.returncode != 0:
        raise SchedulerError(f"Выключить не вышло: {(done.stderr or done.stdout).strip()}")


def remove(*, runner: Runner | None = None) -> bool:
    done = _run(runner or subprocess.run, ["/Delete", "/TN", TASK_PATH, "/F"])
    return done.returncode == 0


def status(*, runner: Runner | None = None) -> TaskStatus:
    """Есть ли задание, включено ли оно и когда срабатывало."""
    done = _run(runner or subprocess.run, ["/Query", "/TN", TASK_PATH, "/FO", "LIST", "/V"])
    if done.returncode != 0:
        return TaskStatus(exists=False)
    values: dict[str, str] = {}
    for line in (done.stdout or "").splitlines():
        key, _, value = line.partition(":")
        if value.strip():
            values[key.strip().lower()] = value.strip()
    state = values.get("состояние", values.get("status", "")).lower()
    last_result = values.get("код последнего запуска", values.get("last result", ""))
    if last_result.strip() in (str(NEVER_RAN), hex(NEVER_RAN)):
        last_result = "ещё не запускалось"
    return TaskStatus(
        exists=True,
        enabled="отключ" not in state and "disabled" not in state,
        next_run=values.get("время следующего запуска", values.get("next run time", "")),
        last_run=values.get("время прошлого запуска", values.get("last run time", "")),
        last_result=last_result,
    )
