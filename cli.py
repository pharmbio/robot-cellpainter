import argparse

from robots import Config, configs
from utils import show

import robots
from moves import movelists

import protocol

def main():
    parser = argparse.ArgumentParser(description='Make the lab robots do things.', )
    parser.add_argument('--config', metavar='NAME', type=str, default='dry_run', help='Config to use')
    parser.add_argument('--list-config', action='store_true', help='List available configs')

    parser.add_argument('--cell-paint', metavar='N', type=int, default=None, help='Cell paint N plates stored in L1, L2, ..')

    parser.add_argument('--wash', action='store_true', help='Run a test program on the washer')
    parser.add_argument('--disp', action='store_true', help='Run a test program on the dispenser')
    parser.add_argument('--incu-put', metavar='POS', type=str, default=None, help='Put the plate in the transfer station to the argument position POS (L1, .., R1, ..).')
    parser.add_argument('--incu-get', metavar='POS', type=str, default=None, help='Get the plate in the argument position POS. It ends up in the transfer station.')

    parser.add_argument('--list-robotarm-programs', action='store_true', help='List the robot arm programs')
    parser.add_argument('--robotarm', action='store_true', help='Run robot arm')
    parser.add_argument('--robotarm-speed', metavar='N', type=int, default=80, help='Robot arm speed [1-100]')
    parser.add_argument('program_name', type=str, nargs='*', help='Robot arm program name to run')

    args = parser.parse_args()
    print(f'args =', show(args.__dict__))

    config_name = args.config.replace('-', '_')
    try:
        config: Config = configs[config_name]
    except KeyError:
        raise ValueError(f'Unknown {config_name = }. Available: {show(configs.keys())}')

    print(f'Using config =', show(config))

    if args.cell_paint:
        protocol.main(num_plates=args.cell_paint, config=config)

    elif args.robotarm:
        robots.get_robotarm(config).set_speed(args.robotarm_speed).close()
        for name in args.program_name:
            if name in movelists:
                robots.robotarm_cmd(name).execute(config)
            else:
                print('Unknown program:', name)

    elif args.list_robotarm_programs:
        for name in movelists.keys():
            print(name)

    elif args.wash:
        robots.wash_cmd('automation/2_4_6_W-3X_FinalAspirate_test.LHC', est=0).execute(config)
        robots.wait_for_ready_cmd('wash').execute(config)

    elif args.disp:
        robots.disp_cmd('automation/1_D_P1_30ul_mito.LHC', est=0).execute(config)
        robots.wait_for_ready_cmd('disp').execute(config)

    elif args.incu_put:
        robots.incu_cmd('put', args.incu_put, est=0).execute(config)
        robots.wait_for_ready_cmd('incu').execute(config)

    elif args.incu_get:
        robots.incu_cmd('get', args.incu_get, est=0).execute(config)
        robots.wait_for_ready_cmd('incu').execute(config)

    else:
        parser.print_help()

if __name__ == '__main__':
    main()