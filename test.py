#!/usr/bin/env pypy
# -*- coding: utf-8 -*-

from __future__ import print_function
import os
import re
import sys
import time
import subprocess
import signal
import argparse
import importlib
import itertools
import multiprocessing
import random
import unittest
import warnings

import sunfish
import tools

###############################################################################
# Playing test
###############################################################################

class Tests(unittest.TestCase):
    def setUp(self):
        # We don't bother about closing files, since they are just part of the test
        warnings.simplefilter("ignore", ResourceWarning)
        self.perft_file = os.path.join(os.path.dirname(__file__), 'tests/queen.fen')
        test_trees = [tools.expand_position(tools.parseFEN(tools.parseEPD(line)[0])) for line in open(self.perft_file)]
        self.positions = list(itertools.chain(*[tools.flatten_tree(tree, depth=2) for tree in test_trees]))

    def test_fen(self):
        fen_file = os.path.join(os.path.dirname(__file__), 'tests/chessathome_openings.fen')
        for fen in open(fen_file):
            fen = fen.strip()
            pos = tools.parseFEN(fen)
            fen1 = tools.renderFEN(pos)
            self.assertEqual(fen, fen1, "Sunfish didn't correctly reproduce the FEN."
                    + repr(pos))

    def test_fen2(self):
        initial = sunfish.Position(sunfish.initial, 0, (True,True), (True,True), 0, 0)
        for pos in tools.flatten_tree(tools.expand_position(initial),3):
            fen = tools.renderFEN(pos)
            self.assertEqual(fen.split()[1], 'wb'[tools.get_color(pos)], "Didn't read color correctly")
            pos1 = tools.parseFEN(fen)
            self.assertEqual(pos.board, pos1.board, "Sunfish didn't correctly reproduce the board")
            self.assertEqual(pos.wc, pos1.wc)
            self.assertEqual(pos.bc, pos1.bc)
            ep =  pos.ep  if not pos.board[pos.ep].isspace() else 0
            ep1 = pos1.ep if not pos1.board[pos1.ep].isspace() else 0
            kp =  pos.kp  if not pos.board[pos.kp].isspace() else 0
            kp1 = pos1.kp if not pos1.board[pos1.kp].isspace() else 0
            self.assertEqual(ep, ep1)
            self.assertEqual(kp, kp1)

    def test_perft(self):
        success = allperft(open(self.perft_file), depth=2, verbose=False)
        self.assertTrue(success)

    def test_san(self):
        pgn_file = os.path.join(os.path.dirname(__file__), 'tests/pgns.pgn')
        for line in open(pgn_file):
            msans = [msan for i, msan in enumerate(line.split()[:-1]) if i%3]
            pos = tools.parseFEN(tools.FEN_INITIAL)
            for i, msan in enumerate(msans):
                move = tools.parseSAN(pos, msan)
                if re.search('=[BNR]', msan):
                    # Sunfish doesn't support underpromotion
                    break
                msan_back = tools.renderSAN(pos, move)
                self.assertEqual(msan_back, msan,
                                 "Sunfish didn't correctly reproduce the SAN move")
                pos = pos.move(move)

    def test_selfplay(self):
        pos = tools.parseFEN(tools.FEN_INITIAL)
        for d in range(200):
            m, score = sunfish.Searcher().search(pos, .1)
            if m is None:
                self.assertTrue(score == 0 or abs(score) >= sunfish.MATE_LOWER)
                break
            pos = pos.move(m)

    def test_value(self):
        for pos in self.positions:
            score = 0
            for i,p in enumerate(pos.board):
                if p.isupper(): score += sunfish.pst[p][i]
                if p.islower(): score -= sunfish.pst[p.upper()][119-i]
            self.assertEqual(pos.score, score,
                    ' '.join(pos.board) + repr(pos))
            # Rotated scores
            self.assertEqual(pos.score, -pos.rotate().score)
            score = 0
            for i,p in enumerate(pos.rotate().board):
                if p.isupper(): score += sunfish.pst[p][i]
                if p.islower(): score -= sunfish.pst[p.upper()][119-i]
            self.assertEqual(pos.rotate().score, score)

    def test_xboard(self):
        test_xboard('pypy3', verbose=False)
        test_xboard('python3', verbose=False)
        test_xboard('python', verbose=False)
        test_xboard('pypy', verbose=False)

###############################################################################
# Playing test
###############################################################################

def selfplay(secs=1):
    """ Start a game sunfish vs. sunfish """
    pos = tools.parseFEN(tools.FEN_INITIAL)
    for d in range(200):
        # Always print the board from the same direction
        board = pos.board if d % 2 == 0 else pos.rotate().board
        print(' '.join(board))
        m, _ = sunfish.Searcher().search(pos, secs)
        if m is None:
            print("Game over")
            break
        print("\nmove", tools.mrender(pos, m))
        pos = pos.move(m)


def self_arena(version1, version2, games, secs, plus):
    print('Playing {} games of {} vs. {} at {} secs/game + {} secs/move'
            .format(games, version1, version2, secs, plus))
    openings_file = os.path.join(os.path.dirname(__file__), 'tests/chessathome_openings.fen')
    openings = random.sample(list(open(openings_file)), games)
    pool = multiprocessing.Pool()
    instances = [random.choice([
        (version1, version2, secs, plus, fen),
        (version2, version1, secs, plus, fen)]) for fen in openings]
    wins = 0
    losses = 0
    for i, r in enumerate(pool.imap_unordered(play, instances)):
        if r is None:
            print('-', end='', flush=True)
        if r == version1:
            wins += 1
            print('w', end='', flush=True)
        if r == version2:
            losses += 1
            print('l', end='', flush=True)
        if i % 80 == 79:
            print()
            print('{} wins, {} draws, {} losses out of {}'.format(wins,i+1-wins-losses,losses,i+1))
    print()
    print('Result: {} wins, {} draws, {} losses out of {}'.format(wins,games-wins-losses,losses,games))


def play(version1_version2_secs_plus_fen):
    ''' returns 1 if fish1 won, 0 for draw and -1 otherwise '''
    version1, version2, secs, plus, fen = version1_version2_secs_plus_fen
    modules = [importlib.import_module(version1), importlib.import_module(version2)]
    searchers = []
    for module in modules:
        if hasattr(module, 'Searcher'):
            searchers.append(module.Searcher())
        else: searchers.append(module)
    times = [secs, secs]
    pos = tools.parseFEN(fen)
    seen = set()
    for d in range(200):
        moves_remain = 40
        use = times[d%2]/moves_remain
        t = time.time()
        m, score = searchers[d%2].search(pos, use)
        times[d%2] -= time.time() - t
        times[d%2] += plus
        if times[d%2] < 0:
            pass
        if m is not None:
            pos = pos.move(m)
            # Test repetition draws
            if pos in seen:
                return None
            seen.add(pos)
        else:
            if score == 0:
                return None
            assert score <= -sunfish.MATE_LOWER, "We lost?"
            return version1 if d%2 == 1 else version2
    return None


###############################################################################
# Test Xboard
###############################################################################

class timeout:
    def __init__(self, seconds=1, error_message='Timeout'):
        self.seconds = seconds
        self.error_message = error_message
    def handle_timeout(self, _signum, _frame):
        raise TimeoutError(self.error_message)
    def __enter__(self):
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)
    def __exit__(self, _type, _value, _traceback):
        signal.alarm(0)

def test_xboard(python='python3', verbose=True):
    if verbose:
        print('Xboard test \'%s\'' % python)
    fish = subprocess.Popen(
        [python, '-u', 'tools.py'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        universal_newlines=True)

    def wait_for(regex):
        with timeout(20, '%s was never encountered'%regex):
            while True:
                line = fish.stdout.readline()
                if verbose:
                    print(repr(line))
                if re.search(regex, line):
                    return
    def write(cmd):
        if verbose:
            print('>>>', repr(cmd))
        print(cmd, file=fish.stdin, flush=True)

    try:
        write('xboard')
        write('protover 2')
        wait_for(r'done\s*=\s*1')
        write('usermove e2e4')
        wait_for('move ')
        write('setboard rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1')
        write('usermove e7e5')
        wait_for('move ')
        write('quit')
        with timeout(5, 'quit did not terminate sunfish'):
            fish.wait()
    finally:
        if fish.poll() is None:
            fish.kill()

###############################################################################
# Perft test
###############################################################################

def allperft(f, depth=4, verbose=True):
    import gc
    lines = f.readlines()
    for d in range(1, depth+1):
        if verbose:
            print("Going to depth {}/{}".format(d, depth))
        for line in lines:
            parts = line.split(';')
            if verbose:
                print(parts[0])

            pos, score = tools.parseFEN(parts[0]), int(parts[d])
            res = sum(1 for _ in tools.collect_tree_depth(tools.expand_position(pos), d))
            if res != score:
                print('=========================================')
                print('ERROR at depth %d. Gave %d rather than %d' % (d, res, score))
                print('=========================================')
                print(tools.renderFEN(pos,0))
                sunfish.print_pos(pos)
                #print(' '.join(renderSAN(pos, 0, mov) for mov in pos.gen_moves()))
                print(' '.join(sunfish.render(m[0])+sunfish.render(m[1]) for m in pos.gen_moves()))
                return False
        if verbose:
            print('')
    return True

###############################################################################
# Find mate test
###############################################################################

def allmate(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            print(line)

            pos = tools.parseFEN(line)
            _, score = sunfish.Searcher().search(pos, secs=3600)
            if score < sunfish.MATE_LOWER:
                print("Unable to find mate. Only got score = %d" % score)
                break

def quickdraw(f, depth):
    k, n = 0, 0
    for line in f:
        line = line.strip()
        print(line)
        n += 1

        pos = tools.parseFEN(line)
        searcher = sunfish.Searcher()
        for d in range(depth, 10):
            s0 = searcher.bound(pos, 0, d, root=True)
            s1 = searcher.bound(pos, 1, d, root=True)
            if s0 >= 0 and s1 < 1:
                k += 1
                break
            else:
                print('depth {}, s0 {}, s1 {}'.format(d, s0, s1))
            #print(d, s0, s1, tools.pv(0, pos))
        else:
            print("Fail: Unable to find draw!")
            #return
        print(tools.pv(searcher, pos, False))
    print('Found {}/{} draws'.format(k,n))

def quickmate(f, min_depth=1):
    """ Similar to allmate, but uses the `bound` function directly to only
    search for moves that will win us the game """
    for line in f:
        line = line.strip()
        print(line)

        pos = tools.parseFEN(line)
        searcher = sunfish.Searcher()
        for d in range(min_depth, 99):
            score = searcher.bound(pos, sunfish.MATE_LOWER, d, root=True)
            if score >= sunfish.MATE_LOWER:
                #print(tools.pv(searcher, 0, pos))
                break
            print('Score at depth {}: {}'.format(d, score))
        else:
            print("Unable to find mate. Only got score = %d" % score)
            return
        print(tools.pv(searcher, pos, include_scores=False))

###############################################################################
# Best move test
###############################################################################

def findbest(f, times):
    pos = tools.parseFEN(tools.FEN_INITIAL)
    searcher = sunfish.Searcher()

    print('Printing best move after seconds', times)
    print('-'*60)
    totalpoints = 0
    totaltests = 0
    for line in f:
        fen, opts = tools.parseEPD(line, opt_dict=True)
        if type(opts) != dict or ('am' not in opts and 'bm' not in opts):
            print("Line didn't have am/bm in opts", line, opts)
            continue
        pos = tools.parseFEN(fen)
        # am -> avoid move; bm -> best move
        am = tools.parseSAN(pos,opts['am']) if 'am' in opts else None
        bm = tools.parseSAN(pos,opts['bm']) if 'bm' in opts else None
        print('Looking for am/bm', opts.get('am'), opts.get('bm'))
        points = 0
        print(opts.get('id','unnamed'), end=' ', flush=True)
        for t in times:
            move, _ = searcher.search(pos, t)
            mark = tools.renderSAN(pos,move)
            if am and move != am or bm and move == bm:
                mark += '(1)'
                points += 1
            else:
                mark += '(0)'
            print(mark, end=' ', flush=True)
            totaltests += 1
        print(points)
        totalpoints += points
    print('-'*60)
    print('Total Points: %d/%d', totalpoints, totaltests)

###############################################################################
# Actions
###############################################################################

def add_action(parser, f):
    class LambdaAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            f(namespace)
    parser.add_argument('_action', nargs='?',
        help=argparse.SUPPRESS, action=LambdaAction)

def main():
    parser = argparse.ArgumentParser(
        description='Run various tests for speed and correctness of sunfish.')
    subparsers = parser.add_subparsers()

    p = subparsers.add_parser('perft',
        help='tests for correctness and speed of move generator.')
    p.add_argument('--depth', type=int, default=2)
    p.add_argument('file', type=argparse.FileType('r'),
        help='such as tests/queen.fen.')
    add_action(p, lambda n: allperft(n.file, n.depth))

    p = subparsers.add_parser('quickmate',
        help='uses the `bound` function directly to search for moves that will win us the game.')
    p.add_argument('file', type=argparse.FileType('r'),
        help='such as tests/mate{1,2,3}.fen.')
    p.add_argument('--mindepth', type=int, default=3, metavar='D',
        help='optional minimum number of plies to search for.')
    add_action(p, lambda n: quickmate(n.file, n.mindepth))

    p = subparsers.add_parser('quickdraw',
            help='solve draw puzzles')
    p.add_argument('file', type=argparse.FileType('r'),
        help='such as tests/staltemate2.fen.')
    p.add_argument('--mindepth', type=int, default=3, metavar='D',
        help='optional minimum number of plies to search for.')
    add_action(p, lambda n: quickdraw(n.file, n.mindepth))

    p = subparsers.add_parser('xboard',
        help='starts the tools.py script and runs a few commands.')
    p.add_argument('--python', type=str, default='python',
        help='what version of python to use, e.g. python3, pypy.')
    add_action(p, lambda n: test_xboard(n.python))

    p = subparsers.add_parser('selfplay',
        help='run a simple visual sunfish vs sunfish game.')
    p.add_argument('--sexs', type=int, default=1,
        help='number of seconds to search per move. Default=%(default)s.')
    add_action(p, lambda n: selfplay(n.nodes))

    p = subparsers.add_parser('arena',
        help='run a number of games between two sunfish versions.')
    p.add_argument('fish1', type=str, help='sunfish')
    p.add_argument('fish2', type=str, help='sunfish2')
    p.add_argument('--games', type=int, default=10,
        help='number of games to play. Default=%(default)s.')
    p.add_argument('--seconds', type=float, default=20,
        help='number of seconds to search per game. Default=%(default)s.')
    p.add_argument('--plus', type=float, default=.1,
        help='seconds time increment per move. Default=%(default)s.')
    add_action(p, lambda n: self_arena(n.fish1, n.fish2, n.games, n.seconds, n.plus))

    p = subparsers.add_parser('findbest',
        help='reports the best moves found at certain positions after certain intervals of time.')
    p.add_argument('file', type=argparse.FileType('r'),
        help='tests/ccr_one_hour_test.epd or tests/bratko_kopec_test.epd.')
    p.add_argument('--times', type=int, nargs='+',
        help='a list of times (in seconds) at which to report the best move. Default is %(default)s.',
        default=[15, 30, 60, 120])
    add_action(p, lambda n: findbest(n.file, n.times))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    p = subparsers.add_parser('unittest',
            help='Deprecated: use python -m unittest test.Tests')
    add_action(p, lambda n: unittest.TextTestRunner().run(suite))

    _args, unknown = parser.parse_known_args()
    if unknown:
        print('Notice: unused arguments', ' '.join(unknown))
    if len(sys.argv) == 1:
        parser.print_help()

if __name__ == '__main__':
    main()

