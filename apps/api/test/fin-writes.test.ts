/**
 * Unit tests for the Finance write slice (phase 6 · slice 2b).
 *
 * Two things are worth testing in isolation here, because the live harness
 * compares parsed JSON and so cannot see either of them:
 *   • CPython's JSON decoder errors, which FastAPI puts verbatim into the 422
 *     body as a message and a character offset;
 *   • Python's round(x, 2), which is half-to-even against the double's TRUE
 *     binary value — the expected values below were produced by running the
 *     real interpreter, not by reasoning about them.
 *
 * End-to-end comparison against Python lives in scripts/write-parity.ts.
 */
import { describe, expect, it } from 'vitest';
import { Double } from 'mongodb';
import {
  bodyMissingIssue,
  bodyNotDictIssue,
  jsonInvalidIssue,
  pyJsonLoads,
  PyJsonError,
} from '../src/common/py-body';
import { pyRound2 } from '../src/common/py-round';
import { floatifyClosure, floatifySnapshot, snapshotToBson } from '../src/fin/fin-writes.service';
import { pyDumps } from '../src/common/py-json';

/** Returns [offset, CPython message] for a body the decoder rejects. */
function decodeError(text: string): [number, string] {
  try {
    pyJsonLoads(text);
  } catch (e) {
    if (e instanceof PyJsonError) return [e.pos, e.pyMessage];
    throw e;
  }
  throw new Error(`expected ${JSON.stringify(text)} to fail`);
}

describe('CPython JSON decoder errors', () => {
  // Every row was read off the running Python server on 2026-09-21.
  it.each([
    ['not json', 0, 'Expecting value'],
    ['{', 1, 'Expecting property name enclosed in double quotes'],
    ['{"a"', 4, "Expecting ':' delimiter"],
    ['{"a":}', 5, 'Expecting value'],
    ['{"a":1,}', 7, 'Expecting property name enclosed in double quotes'],
    ['{"a":1}{', 7, 'Extra data'],
    ['[1,2', 4, "Expecting ',' delimiter"],
    ['{"a":"x', 5, 'Unterminated string starting at'],
    ['{"a":"\t"}', 6, 'Invalid control character at'],
    ['{"a":"\\q"}', 6, 'Invalid \\escape'],
    ['{"a":"\\u12"}', 7, 'Invalid \\uXXXX escape'],
    ["{'a':1}", 1, 'Expecting property name enclosed in double quotes'],
    ['  ', 2, 'Expecting value'],
    ['{"a" 1}', 5, "Expecting ':' delimiter"],
    ['tru', 0, 'Expecting value'],
    ['01', 1, 'Extra data'],
    ['-', 0, 'Expecting value'],
  ])('%j fails at %d with %s', (text, pos, msg) => {
    expect(decodeError(text as string)).toEqual([pos, msg]);
  });
});

describe('CPython JSON decoder acceptance', () => {
  it('accepts NaN and Infinity, which JSON.parse rejects', () => {
    expect(() => JSON.parse('{"x": NaN}')).toThrow();
    expect(pyJsonLoads('{"x": NaN}')).toEqual({ x: NaN });
    expect(pyJsonLoads('{"x": Infinity}')).toEqual({ x: Infinity });
    expect(pyJsonLoads('{"x": -Infinity}')).toEqual({ x: -Infinity });
  });

  it('parses the ordinary shapes', () => {
    expect(pyJsonLoads('{"close_date":"2026-09-03","n":1,"f":1.5,"b":true,"z":null}')).toEqual({
      close_date: '2026-09-03',
      n: 1,
      f: 1.5,
      b: true,
      z: null,
    });
    expect(pyJsonLoads('[]')).toEqual([]);
    expect(pyJsonLoads('{}')).toEqual({});
    expect(pyJsonLoads('  {"a":  [1, {"b": 2}] }  ')).toEqual({ a: [1, { b: 2 }] });
  });

  it('handles escapes, including surrogate pairs', () => {
    expect(pyJsonLoads('"a\\nb\\t\\"c\\\\"')).toBe('a\nb\t"c\\');
    expect(pyJsonLoads('"\\u0041\\u00e9"')).toBe('Aé');
    expect(pyJsonLoads('"\\ud83d\\ude00"')).toBe('😀');
  });

  it('lets a later duplicate key win, as CPython does', () => {
    expect(pyJsonLoads('{"a":1,"a":2}')).toEqual({ a: 2 });
  });
});

describe('FastAPI body error envelopes', () => {
  it('builds the json_invalid envelope with offset and ctx', () => {
    expect(jsonInvalidIssue(new PyJsonError(7, 'Extra data'))).toEqual({
      type: 'json_invalid',
      loc: ['body', 7],
      msg: 'JSON decode error',
      input: {},
      ctx: { error: 'Extra data' },
    });
  });

  it('builds the missing and dict_type envelopes', () => {
    expect(bodyMissingIssue().type).toBe('missing');
    expect(bodyMissingIssue().loc).toEqual(['body']);
    const notDict = bodyNotDictIssue('close_date=2026-09-03');
    expect(notDict.type).toBe('dict_type');
    // A non-JSON content-type hands the RAW TEXT through as `input`.
    expect(notDict.input).toBe('close_date=2026-09-03');
  });
});

describe("Python's round(x, 2)", () => {
  // Expected values produced by D:/trk-venv python, not by reasoning.
  it.each([
    [2.675, 2.67], // the classic: the double is below the midpoint
    [0.125, 0.12], // an exact tie, rounded to even
    [0.375, 0.38], // an exact tie, rounded to even the other way
    [0.135, 0.14],
    [1.005, 1.0],
    [2.5, 2.5],
    [20.009999999999998, 20.01],
    [1234.565, 1234.57],
    [0.615, 0.61],
    [52400, 52400],
    [1e-9, 0],
    [123456.789, 123456.79],
  ])('rounds %d to %d', (input, expected) => {
    expect(pyRound2(input)).toBe(expected);
  });

  it('is symmetric about zero, as Python is', () => {
    expect(pyRound2(-2.675)).toBe(-2.67);
    expect(pyRound2(-0.125)).toBe(-0.12);
  });

  it('leaves zero and non-finite values alone', () => {
    expect(pyRound2(0)).toBe(0);
    expect(pyRound2(NaN)).toBeNaN();
    expect(pyRound2(Infinity)).toBe(Infinity);
  });

  it('does NOT use the scale-by-100 shortcut that mis-rounds 2.675', () => {
    // The naive implementation reads 2.675 as a tie and returns 2.68.
    const naive = Math.round(2.675 * 100) / 100;
    expect(naive).toBe(2.68);
    expect(pyRound2(2.675)).toBe(2.67);
  });
});

describe('snapshot value types', () => {
  it('stores balances as BSON doubles, so an integral balance is not an int32', () => {
    const bson = snapshotToBson({ CASH: { in: 52400, out: 0, net: 52400 } });
    const cash = (bson['CASH'] as Record<string, unknown>)['in'];
    expect(cash).toBeInstanceOf(Double);
    expect((cash as Double).value).toBe(52400);
  });

  it('renders an integral balance as 52400.0, not 52400', () => {
    const out = pyDumps(floatifySnapshot({ CASH: { in: 52400, out: 0, net: 52400 } }));
    expect(out).toBe('{"CASH":{"in":52400.0,"out":0.0,"net":52400.0}}');
  });

  it('renders balances read back as BSON doubles the same way', () => {
    const out = pyDumps(floatifySnapshot(snapshotToBson({ CASH: { in: 52400, out: 0.5, net: 52399.5 } })));
    expect(out).toBe('{"CASH":{"in":52400.0,"out":0.5,"net":52399.5}}');
  });

  it('floats the snapshot inside every history entry but leaves counts as ints', () => {
    const doc = floatifyClosure({
      id: 'fdc_1',
      snapshot: { CASH: { in: 1, out: 0, net: 1 } },
      snapshot_source_count: 4,
      history: [
        {
          event: 'closed',
          snapshot: { CASH: { in: 1, out: 0, net: 1 } },
          snapshot_source_count: 4,
        },
        { event: 'reopened', reason: 'x' },
      ],
    });
    const out = pyDumps(doc);
    expect(out).toContain('"snapshot":{"CASH":{"in":1.0,"out":0.0,"net":1.0}}');
    expect(out).toContain('"snapshot_source_count":4');
    expect(out).not.toContain('"snapshot_source_count":4.0');
    expect(out).toContain('{"event":"reopened","reason":"x"}');
  });

  it('preserves account key order, which is the cursor order', () => {
    const snap = { CASH: { in: 1, out: 0, net: 1 }, AR: { in: 2, out: 0, net: 2 } };
    expect(Object.keys(floatifySnapshot(snap) as object)).toEqual(['CASH', 'AR']);
  });
});
