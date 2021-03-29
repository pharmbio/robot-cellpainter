from __future__ import annotations

from dataclasses import dataclass, field, replace, astuple
from typing import *
from datetime import datetime, timedelta

from utils import show
import snoop # type: ignore
snoop.install(pformat=show)
pp: Any

JobId = NewType('JobId', str)

@dataclass(frozen=True)
class Plate:
    id: str
    loc: str
    lid_loc: str = 'self'
    waiting_for: list[JobId | datetime | timedelta] = field(default_factory=list, repr=True)
    queue: list[ProtocolStep] = field(default_factory=list, repr=True)
    meta: Any = field(default=None, repr=False)

    def top(self) -> ProtocolStep:
        return self.queue[0]

    def pop(self) -> Plate:
        return replace(self, queue=self.queue[1:])

H = [21, 19, 17, 15, 13, 11, 9, 7, 5, 3, 1]
I = [i+1 for i in range(42)]
Out = [18] # [ i+1 for i in range(18) ] # todo: measure out_hotel_dist
# Out = [ i+1 for i in range(18) ] # todo: measure out_hotel_dist

if 0:
    # small test version
    H = [21, 19, 17, 15, 13]
    I = [1, 2, 3, 4, 5]
    Out = [18]

h21 = 'h21'

incu_locs: list[str] = [f'i{i}' for i in I]
h_locs:    list[str] = [f'h{i}' for i in H]
r_locs:    list[str] = [f'r{i}' for i in H]
out_locs:  list[str] = [f'out{i}' for i in Out]
lid_locs:  list[str] = [h for h in h_locs if h != h21]

out_locs += r_locs

@dataclass(frozen=True)
class World:
    plates: dict[str, Plate]

    def __getattr__(self, loc: str) -> str:
        if loc in ('shape', 'dtype'):
            raise AttributeError
        for p in self.plates.values():
            if loc == p.loc:
                return p.id
            if loc == p.lid_loc:
                return f'lid({p.id})'
        return 'free'

    # def __getitem__(self, loc: str) -> str:
    __getitem__ = __getattr__

    def update(self, p: Plate) -> World:
        return replace(self, plates={**self.plates, p.id: p})

    def transition(self, p: Plate, cmds: list[run]=[]) -> Transition:
        return Transition(w=self.update(p), cmds=cmds)

@dataclass(frozen=True)
class run:
    device: str
    arg: Any | None = None
    id: JobId | None = None

@dataclass(frozen=True)
class Transition:
    w: World
    cmds: list[run] = field(default_factory=list)
    prio: int = 0
    def __rshift__(self, other: Transition) -> Transition:
        return Transition(other.w, self.cmds + other.cmds, max(self.prio, other.prio))

def world_locations(w: World) -> dict[str, str]:
    locs: list[str] = 'wash disp incu'.split()
    locs += incu_locs
    locs += h_locs
    locs += r_locs
    locs += out_locs
    return {loc: w[loc] for loc in locs}

def active_count(w: World) -> int:
    locs: list[str] = 'wash disp incu'.split()
    locs += h_locs
    # locs += r_locs
    return sum(
        1 for p in w.plates.values()
        if p.loc in locs
        if p.queue
        # ie not inside incubator and not in output
    )

@dataclass
class UniqueSupply:
    count: int = 0
    def __call__(self, prefix: str='') -> str:
        self.count += 1
        return f'{prefix}({self.count})'

    def reset(self) -> None:
        self.count = 0

unique = UniqueSupply()

from abc import ABC, abstractmethod

class ProtocolStep(ABC):
    @abstractmethod
    def step(self, p: Plate, w: World) -> Transition | None:
        pass

    def prio(self) -> int:
        return 0

@dataclass(frozen=True)
class incu_pop(ProtocolStep):
    def step(self, p: Plate, w: World) -> Transition | None:
        if p.loc in incu_locs and w.incu == 'free':
            id = JobId(unique('incu'))
            return w.transition(
                replace(p, loc='incu', waiting_for=[id]),
                [run('incu_get', p.loc, id=id)]
            )
        return None

@dataclass(frozen=True)
class incu_put(ProtocolStep):
    timedelta: timedelta
    def step(self, p: Plate, w: World) -> Transition | None:
        if p.loc == h21 and p.lid_loc == 'self' and w.incu == 'free':
            for incu_loc in incu_locs:
                if w[incu_loc] == 'free':
                    id = JobId(unique('incu'))
                    return w.transition(
                        replace(p, loc=incu_loc, waiting_for=[id, self.timedelta]),
                        [
                            run('robot', 'generated/incu_put'),
                            run('incu_put', incu_loc, id=id),
                        ]
                    )
        return None

    def prio(self) -> int:
        return 2

@dataclass(frozen=True)
class wash(ProtocolStep):
    arg1: str | None = None
    arg2: str | None = None
    def step(self, p: Plate, w: World) -> Transition | None:
        if p.loc == h21 and p.lid_loc != 'self' and w.wash == 'free':
            id = JobId(unique('wash'))
            return w.transition(
                replace(p, loc='wash', waiting_for=[id]),
                [
                    run('robot', 'generated/wash_put'),
                    run('wash', [self.arg1, self.arg2], id=id),
                ],
            )
        return None

    def prio(self) -> int:
        return 3

@dataclass(frozen=True)
class disp(ProtocolStep):
    arg1: str | None = None
    arg2: str | None = None
    def step(self, p: Plate, w: World) -> Transition | None:
        if p.loc == h21 and p.lid_loc != 'self' and w.disp == 'free':
            id = JobId(unique('disp'))
            return w.transition(
                replace(p, loc='disp', waiting_for=[id]),
                [
                    run('robot', 'generated/disp_put'),
                    run('disp', [self.arg1, self.arg2], id=id)
                ],
            )
        return None

    def prio(self) -> int:
        return 3

@dataclass(frozen=True)
class RT_incu(ProtocolStep):
    timedelta: timedelta
    def step(self, p: Plate, w: World) -> Transition | None:
        if p.loc == 'h21' and p.lid_loc == 'self':
            for r_loc in r_locs:
                if w[r_loc] == 'free':
                    return w.transition(
                        replace(p, loc=r_loc, waiting_for=[self.timedelta]),
                        [run('robot', f'generated/{r_loc}_put')]
                    )
        return None

    def prio(self) -> int:
        return 1


@dataclass(frozen=True)
class to_output_hotel(ProtocolStep):
    def step(self, p: Plate, w: World) -> Transition | None:
        if p.loc == 'h21' and p.lid_loc == 'self':
            for out_loc in out_locs:
                if w[out_loc] == 'free':
                    return w.transition(
                        replace(p, loc=out_loc),
                        [run('robot', f'generated/{out_loc}_put')]
                    )
        return None

def moves(p: Plate, w: World) -> Iterator[Transition]:
    assert isinstance(p.waiting_for, list)
    if p.waiting_for:
        return

    # disp to h21
    if p.loc == 'disp' and w.h21 == 'free':
        assert not p.waiting_for
        yield w.transition(
            replace(p, loc=h21),
            [run('robot', 'generated/disp_get')]
        )

    # wash to h21
    if p.loc == 'wash' and w.h21 == 'free':
        assert not p.waiting_for
        yield w.transition(
            replace(p, loc=h21),
            [run('robot', 'generated/wash_get')]
        )

    # incu to h21
    if p.loc == 'incu' and w.h21 == 'free':
        assert not p.waiting_for
        yield w.transition(
            replace(p, loc=h21),
            [run('robot', 'generated/incu_get')]
        )

    # RT to h21
    if p.loc in r_locs and w.h21 == 'free':
        assert not p.waiting_for
        yield w.transition(
            replace(p, loc=h21),
            [run('robot', f'generated/{p.loc}_get')]
        )

    # h## to h21
    if p.loc in h_locs and w.h21 == 'free':
        yield w.transition(
            replace(p, loc=h21),
            [run('robot', f'generated/{p.loc}_get')]
        )

    # h21 to h##
    if p.loc == h21:
        for h_loc in h_locs:
            if w[h_loc] == 'free':
                yield w.transition(
                    replace(p, loc=h_loc),
                    [run('robot', f'generated/{h_loc}_put')]
                )
                break

    # lid: move lid on h## to self
    if p.loc == h21 and p.lid_loc in lid_locs:
        yield w.transition(
            replace(p, lid_loc='self'),
            [run('robot', f'generated/lid_{p.lid_loc}_get')],
        )

    # delid: move lid on self to h##
    if p.loc == h21 and p.lid_loc == 'self':
        for lid_loc in lid_locs:
            if w[lid_loc] == 'free':
                yield w.transition(
                    replace(p, lid_loc=lid_loc),
                    [run('robot', f'generated/lid_{lid_loc}_put')],
                )
                break

def minutes(m: int) -> timedelta:
    return timedelta(minutes=m)

from collections import deque
import random

from typing import *

@dataclass(frozen=True)
class BfsOpts:
    max_fuel: int=1000
    shuffle_prob: float=0

def bfs_iter(w0: World, opts: BfsOpts=BfsOpts()) -> Iterator[Transition]:
    q: deque[Transition] = deque([Transition(w0)])
    visited: set[str] = set()
    solved: set[str] = set()
    fuel = opts.max_fuel
    while q and fuel > 0:
        fuel -= 1
        if opts.shuffle_prob and random.random() < opts.shuffle_prob:
            random.shuffle(q)
        t = q.popleft()
        w = t.w
        rw = repr(w)
        if rw in visited:
            continue
        visited.add(rw)
        collision = [
            (p, q)
            for p in w.plates.values()
            for q in w.plates.values()
            if p.id < q.id
            if any((
                p.loc == q.loc,
                p.lid_loc != 'self' and p.lid_loc == q.lid_loc,
            ))
        ]
        assert not collision, pp(collision)
        for p in w.plates.values():
            if p.waiting_for:
                continue
            if not p.queue:
                continue
            if p.id not in solved and (res := p.top().step(p.pop(), w)):
                # keep some slots free for lids and rearranges
                if active_count(res.w) + 3 < len(h_locs):
                    solved.add(p.id)
                    yield replace(t >> res, prio=p.top().prio())
            for res in moves(p, w):
                if res:
                    q.append(t >> res)
    return None

def bfs(w0: World, opts: BfsOpts=BfsOpts()) -> Transition | None:
    first: Transition | None = None
    max_prio = max((0, *(p.top().prio() for p in w0.plates.values() if p.queue)))
    for res in bfs_iter(w0, opts):
        if res.prio == max_prio:
            return res
        if not first:
            first = res
    return first

def execute_robot(prog: str):
    import socket
    import re
    if nogripper:
        prog = prog.replace('generated', 'generated_nogripper')
    prog_str = open(pp(prog), 'rb').read()
    prog_name = prog.split('/')[-1]
    needle = f'Program {prog_name} completed'.encode()
    # pp(needle)
    assert needle in prog_str
    if 0:
        print('dry run', prog)
        return
    print('connecting to robot...')
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((robot_host, robot_port))
    print('connected!')
    s.sendall(prog_str)
    while True:
        data = s.recv(4096)
        # RuntimeExceptionMessage, looks like:
        # b'syntax_error_on_line:4:    movej([0.5, -1, -2, 0, 0, -0], a=0.25, v=1.0):'
        # b'compile_error_name_not_found:getactual_joint_positions:'
        # b'SECONDARY_PROGRAM_EXCEPTION_XXXType error: str_sub takes exact'
        for m in re.findall(b'([\x20-\x7e]*(?:error|EXCEPTION)[\x20-\x7e]*)', data):
            m = m.decode()
            pp(m)

        # KeyMessage, looks like:
        # PROGRAM_XXX_STARTEDtestmove2910
        # PROGRAM_XXX_STOPPEDtestmove2910
        for m in re.findall(b'PROGRAM_XXX_(\w*)', data):
            m = m.decode()
            pp(m)

        if needle in data:
            print(f'program {prog_name} completed!')
            break
    s.close()

# Use start-proxies.sh to forward robot to localhost
robot_host = 'localhost'
robot_port = 30001
nogripper = False

def test_robot():
    from glob import glob
    for path in glob('./generated/*'):
        execute_robot(path)

    # execute_robot('./generated/disp_put')

execute_robot('./generated/out5_put')

if 0:
    execute_robot('./generated/lid_h19_put')

    execute_robot('./generated/incu_put')
    execute_robot('./generated/incu_get')

    execute_robot('./generated/disp_put')
    execute_robot('./generated/disp_get')

    execute_robot('./generated/wash_put')
    execute_robot('./generated/wash_get')

    execute_robot('./generated/r19_put')
    execute_robot('./generated/r19_get')

    execute_robot('./generated/h17_put')
    execute_robot('./generated/h17_get')

    execute_robot('./generated/lid_h19_get')


# execute_robot('./generated/h19_put')
# execute_robot('./generated/r21_put')
# execute_robot('./generated/r19_put')
# execute_robot('./generated/r21_get')
# execute_robot('./generated/r19_get')
# execute_robot('./generated/out18_put')
# execute_robot('./generated/wash_get')
# test_robot()


def execute_incu_get(loc, id):
    print('dry run: execute_incu_get', (loc, id), sep='')
    pass

def execute_incu_put(loc, id):
    print('dry run: execute_incu_put', (loc, id), sep='')
    pass

def execute_wash(args, id):
    print('dry run: execute_wash', (args, id), sep='')
    pass

def execute_disp(args, id):
    print('dry run: execute_disp', (args, id), sep='')
    pass

def execute_cmd(cmd: run):
    if cmd.device in 'robot incu_get incu_put disp wash'.split():
        args = [cmd.arg]
        args = [arg for arg in args if arg is not None]
        kws = dict()
        if cmd.id:
            kws['id'] = cmd.id
        globals()[f'execute_{cmd.device}'](*args, **kws)
    else:
        raise ValueError(f'No such device: {cmd.device}')

# Cell Painting Workflow
protocol: list[ProtocolStep] = [
    # 2 Compound treatment: Remove (80%) media of all wells
    incu_pop(),
    wash(),

    # 3 Mitotracker staining
    disp('peripump 1', 'mitotracker solution'),
    incu_put(minutes(30)),
    incu_pop(),
    wash('pump D', 'PBS'),

    # 4 Fixation
    disp('Syringe A', '4% PFA'),
    RT_incu(minutes(20)),
    wash('pump D', 'PBS'),

    # 5 Permeabilization
    disp('Syringe B', '0.1% Triton X-100 in PBS'),
    RT_incu(minutes(20)),
    wash('pump D', 'PBS'),

    # 6 Post-fixation staining
    disp('peripump 2', 'staining mixture in PBS'),
    RT_incu(minutes(20)),
    wash('pump D', 'PBS'),

    # 7 Imaging
    to_output_hotel(),
]


p0: list[Plate] = [
    Plate('Ada', incu_locs[0], queue=protocol),
    Plate('Bob', incu_locs[1], queue=protocol),
    Plate('Cal', incu_locs[2], queue=protocol),
    Plate('Deb', incu_locs[3], queue=protocol),
    Plate('Eve', incu_locs[4], queue=protocol),
    Plate('Fei', incu_locs[5], queue=protocol),
    Plate('Gil', incu_locs[6], queue=protocol),
    Plate('Hal', incu_locs[7], queue=protocol),
    Plate('Ivy', incu_locs[8], queue=protocol),
    Plate('Joe', incu_locs[9], queue=protocol),
    Plate('Ad2', incu_locs[10], queue=protocol),
    Plate('Bo2', incu_locs[11], queue=protocol),
    Plate('Ca2', incu_locs[12], queue=protocol),
    Plate('De2', incu_locs[13], queue=protocol),
    Plate('Ev2', incu_locs[14], queue=protocol),
    Plate('Fe2', incu_locs[15], queue=protocol),
    Plate('Gi2', incu_locs[16], queue=protocol),
    Plate('Ha2', incu_locs[17], queue=protocol),
    Plate('Iv2', incu_locs[18], queue=protocol),
    Plate('Jo2', incu_locs[19], queue=protocol),
    Plate('Ad3', incu_locs[20], queue=protocol),
    Plate('Bo3', incu_locs[21], queue=protocol),
    Plate('Ca3', incu_locs[22], queue=protocol),
    Plate('De3', incu_locs[23], queue=protocol),
    Plate('Ev3', incu_locs[24], queue=protocol),
    Plate('Fe3', incu_locs[25], queue=protocol),
    Plate('Gi3', incu_locs[26], queue=protocol),
    Plate('Ha3', incu_locs[27], queue=protocol),
    Plate('Iv3', incu_locs[28], queue=protocol),
    Plate('Jo3', incu_locs[29], queue=protocol),
][:len(out_locs)][:16]

w0 = World(dict({p.id: p for p in p0}))

def sim(w: World, shuffle_prob: float=0.0, advance_prob: float=0.0):

    pp('sim')

    all_cmds: list[run] = []

    while 1:
        res = bfs(w, BfsOpts(shuffle_prob=shuffle_prob, max_fuel=1000))

        if res:
            w = res.w
            all_cmds += res.cmds
            print(*[p.loc for p in w.plates.values()], sep='\t')

        times: list[datetime] = []

        any_finished = False

        for p in w.plates.values():
            if p.waiting_for:
                top, *rest = p.waiting_for
                if isinstance(top, str):
                    w = w.update(replace(p, waiting_for=rest))
                    all_cmds += [run('finished', p.loc, id=top)]
                    any_finished = True
                elif isinstance(top, timedelta):
                    time = datetime.now() + top
                    times += [time]
                    w = w.update(replace(p, waiting_for=[time, *rest]))
                elif isinstance(top, datetime):
                    times += [top]
                    break
                else:
                    raise ValueError

        times = list(sorted(times))
        if not times and not res and not any_finished:
            break

        if times and (not res or random.random() < advance_prob):
            now = times[0]
            for p in w.plates.values():
                if p.waiting_for:
                    top, *rest = p.waiting_for
                    if isinstance(top, datetime) and top <= now:
                        all_cmds += [run('wait', (p.loc, top))]
                        w = w.update(replace(p, waiting_for=rest))

    print('done?')
    pp(all_cmds, len(all_cmds))
    pp({
        p.id: (*astuple(p)[:4], len(p.queue))
        for p in w.plates.values()
    })
    pp(w.plates)
    # pp(world_locations(w))

def execute(w: World, advance_prob: float=0.5):
    pp('execute')
    steps = 0

    while 1:
        steps += 1
        res = bfs(w)

        if res:
            for cmd in res.cmds:
                execute_cmd(cmd)
            w = res.w
            print(*[p.loc for p in w.plates.values()], sep='\t')

        # check for timeouts & ready
        times: list[datetime] = []

        any_finished = False

        for p in w.plates.values():
            if p.waiting_for:
                top, *rest = p.waiting_for
                if isinstance(top, str):
                    w = w.update(replace(p, waiting_for=rest))
                    print('finished', p.loc, top)
                    any_finished = True
                elif isinstance(top, timedelta):
                    time = datetime.now() + top
                    times += [time]
                    w = w.update(replace(p, waiting_for=[time, *rest]))
                elif isinstance(top, datetime):
                    times += [top]
                    break
                else:
                    raise ValueError

        times = list(sorted(times))
        if not times and not res and not any_finished:
            pp(w.plates)
            break

        if times and (not res or random.random() < advance_prob):
            now = times[0]
            for p in w.plates.values():
                if p.waiting_for:
                    top, *rest = p.waiting_for
                    if isinstance(top, datetime) and top <= now:
                        print('wait', p.loc, top)
                        w = w.update(replace(p, waiting_for=rest))

    print('done!', steps)

# execute(w0)
