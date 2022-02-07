from __future__ import annotations
from dataclasses import *
from typing import *

import math
from datetime import datetime, timedelta

from . import utils
from .commands import Metadata, Command, Checkpoint, BiotekCmd, Duration, Info

@dataclass(frozen=True)
class Running:
    '''
    Anything that does not grow without bound
    '''
    entries: list[LogEntry] = field(default_factory=list)
    world: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class RuntimeMetadata:
    pid: int
    git_HEAD: str
    log_filename: str
    estimates_pickle_file: str
    program_pickle_file: str
    host: str

@dataclass(frozen=True)
class LogEntry:
    log_time: str           = ''
    t: float                = -1.0
    t0: float | None        = None
    metadata: Metadata      = field(default_factory=lambda: Metadata())
    cmd: Command | None     = None
    err: Error | None       = None
    msg: str | None         = None
    running: Running | None = None
    runtime_metadata: RuntimeMetadata | None = None

    def init(
        self,
        log_time: str,
        t: float,
        t0: float | None = None
    ) -> LogEntry:
        return replace(self, log_time=log_time, t=t, t0=t0)

    def add(
        self,
        metadata: Metadata = Metadata(),
        msg: str = '',
        err: Error | None = None
    ) -> LogEntry:
        if self.msg:
            msg = self.msg + '; ' + msg
        if err:
            assert not self.err
        return replace(self, metadata=self.metadata.merge(metadata), msg=msg, err=err)

    @property
    def duration(self) -> float | None:
        t0 = self.t0
        if isinstance(t0, float):
            return round(self.t - t0, 3)
        else:
            return None

    def is_end(self):
        return isinstance(self.t0, float)

    def is_end_or_inf(self):
        return self.is_end() or isinstance(self.cmd, Info)

    def machine(self):
        try:
            assert self.cmd
            s = self.cmd.required_resource()
            return s
        except:
            return None

    def countdown(self, t_now: float):
        return countdown(t_now, self.t)

    def strftime(self, format: str) -> str:
        return datetime.fromisoformat(self.log_time).strftime(format)

def countdown(t_now: float, to: float):
    return math.ceil(to - math.ceil(t_now))

@dataclass(frozen=True)
class Error:
    message: str
    traceback: str | None = None
    fatal: bool = True

class Log(list[LogEntry]):
    @staticmethod
    def from_jsonl(filename: str):
        return Log(utils.serializer.from_jsonl(filename))

    def write_jsonl(self, filename: str):
        return utils.serializer.write_jsonl(self, filename)

    def finished(self) -> set[str]:
        return {
            i
            for x in self
            if x.is_end_or_inf()
            if (i := x.metadata.id)
        }

    def ids(self) -> set[str]:
        return {
            i
            for x in self
            if (i := x.metadata.id)
        }

    def checkpoints(self) -> dict[str, float]:
        return {
            x.cmd.name: x.t
            for x in self
            if isinstance(x.cmd, Checkpoint)
        }

    def durations(self) -> dict[str, float]:
        return {
            x.cmd.name: d
            for x in self
            if isinstance(x.cmd, Duration)
            if (d := x.duration) is not None
        }

    def group_durations(self: Log):
        groups = utils.group_by(self.durations().items(), key=lambda s: s[0].rstrip(' 0123456789'))
        out: dict[str, list[str]] = {}
        def key(kv: tuple[str, Any]):
            s, _ = kv
            if s.startswith('plate'):
                _plate, i, *what = s.split(' ')
                return f' plate {" ".join(what)} {int(i):03}'
            else:
                return s
        for k, vs in sorted(groups.items(), key=key):
            if k.startswith('plate'):
                _plate, i, *what = k.split(' ')
                k = f'plate {int(i):>2} {" ".join(what)}'
            out[k] = [utils.pp_secs(v) for _, v in vs]
        return out

    def group_durations_for_display(self):
        for k, vs in self.group_durations().items():
            yield k + ' [' + ', '.join(vs) + ']'

    def errors(self, current_runtime_only: bool=True) -> list[tuple[Error, LogEntry]]:
        start = 0
        if current_runtime_only:
            for i, x in list(enumerate(self))[::-1]:
                if x.running:
                    start = i
                    break
        return [
            (err, x)
            for x in self[start:]
            if (err := x.err)
        ]

    def section_starts(self) -> dict[str, float]:
        return {
            section: x.t
            for x in self
            if (section := x.metadata.section)
        }

    def min_t(self):
        return min((x.t for x in self), default=0.0)

    def max_t(self):
        return max((x.t for x in self), default=0.0)

    def length(self):
        return self.max_t() - self.min_t()

    def group_by_section(self, first_section_name: str='begin') -> dict[str, Log]:
        out = {first_section_name: Log()}
        xs = Log()
        for x in sorted(self, key=lambda e: e.t):
            if section := x.metadata.section:
                xs = Log()
                out[section] = xs
            xs.append(x)
        if not out[first_section_name]:
            out.pop(first_section_name)
        out = {
            k: v if not next_kv else Log(v + [LogEntry(t=next_kv[1].min_t() - 0.05)])
            for (k, v), next_kv in utils.iterate_with_next(list(out.items()))
        }
        return out

    def running(self) -> Running | None:
        for x in self[::-1]:
            if m := x.running:
                return m

    def runtime_metadata(self) -> RuntimeMetadata | None:
        for x in self[::-1]:
            if m := x.runtime_metadata:
                return m

    def zero_time(self) -> datetime:
        for x in self[::-1]:
            return datetime.fromisoformat(x.log_time) - timedelta(seconds=x.t)
        raise ValueError('Empty log')

    def is_completed(self) -> bool:
        return any(
            x.metadata.completed
            for x in self
        )

    def num_plates(self) -> int:
        return int(max((p for x in self if (p := x.metadata.plate_id)), default='0'))

    def drop_boring(self) -> Log:
        return Log(
            x
            for x in self
            if not isinstance(x.cmd, BiotekCmd) or not x.cmd.action == 'Validate'
        )

    def where(self, p: Callable[[LogEntry], Any]) -> Log:
        return Log(
            x
            for x in self
            if p(x)
        )

    def add(self, metadata: Metadata) -> Log:
        return Log(
            x.add(metadata)
            for x in self
        )

utils.serializer.register(globals())