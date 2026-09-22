/**
 * CPython `json.loads` compatibility, for FastAPI's request-body 422.
 *
 * `JSON.parse` cannot be used here for two reasons:
 *   • its error messages and offsets are engine-specific, while FastAPI puts
 *     CPython's message in `ctx.error` and CPython's character offset in
 *     `loc[1]`, both of which are part of the response body;
 *   • CPython's decoder ACCEPTS `NaN`, `Infinity` and `-Infinity`, which
 *     `JSON.parse` rejects. A client sending `{"x": NaN}` gets past parsing in
 *     Python, so it must get past parsing here too.
 *
 * Offsets and messages below were verified against the running Python server
 * on 2026-09-21; the table is in
 * docs/migration/PHASE6-SLICE2B-FINANCE-WRITES-PLAN.md.
 *
 * Scope note: this reproduces the decoder's *errors*. It does not reproduce
 * CPython's duplicate-key or big-integer behaviour beyond what the routes in
 * this slice can observe.
 */

export class PyJsonError extends Error {
  constructor(
    readonly pos: number,
    readonly pyMessage: string,
  ) {
    super(pyMessage);
  }
}

/** CPython's json whitespace set — NOT the same as JS `\s`. */
const WS = ' \t\n\r';

const ESCAPES: Record<string, string> = {
  '"': '"',
  '\\': '\\',
  '/': '/',
  b: '\b',
  f: '\f',
  n: '\n',
  r: '\r',
  t: '\t',
};

class Scanner {
  private i = 0;

  constructor(private readonly s: string) {}

  private ws(): void {
    while (this.i < this.s.length && WS.includes(this.s[this.i] as string)) this.i += 1;
  }

  private fail(msg: string, at = this.i): never {
    throw new PyJsonError(at, msg);
  }

  /** Entry point: a whole document, with CPython's "Extra data" trailing check. */
  parse(): unknown {
    this.ws();
    const value = this.value();
    this.ws();
    if (this.i !== this.s.length) this.fail('Extra data');
    return value;
  }

  private value(): unknown {
    if (this.i >= this.s.length) this.fail('Expecting value');
    const c = this.s[this.i] as string;
    if (c === '"') return this.string();
    if (c === '{') return this.object();
    if (c === '[') return this.array();
    if (this.lit('null')) return null;
    if (this.lit('true')) return true;
    if (this.lit('false')) return false;
    // CPython accepts these three constants; JSON.parse does not.
    if (this.lit('NaN')) return NaN;
    if (this.lit('Infinity')) return Infinity;
    if (this.lit('-Infinity')) return -Infinity;
    const n = this.number();
    if (n === undefined) this.fail('Expecting value');
    return n;
  }

  private lit(word: string): boolean {
    if (this.s.startsWith(word, this.i)) {
      this.i += word.length;
      return true;
    }
    return false;
  }

  /**
   * CPython's NUMBER_RE: -?(0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?
   * A partial match simply does not match, which is why `01` parses as `0`
   * and then reports "Extra data" at offset 1 rather than a number error.
   */
  private number(): number | undefined {
    const m = /^-?(?:0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?/.exec(this.s.slice(this.i));
    if (!m || m[0] === '') return undefined;
    this.i += m[0].length;
    // An integer with no fraction/exponent is an int in Python; both render the
    // same through our JSON writer, so a JS number is sufficient here.
    return Number(m[0]);
  }

  private string(): string {
    const start = this.i; // the opening quote, which "Unterminated" reports
    this.i += 1;
    let out = '';
    for (;;) {
      if (this.i >= this.s.length) this.fail('Unterminated string starting at', start);
      const c = this.s[this.i] as string;
      if (c === '"') {
        this.i += 1;
        return out;
      }
      if (c === '\\') {
        this.i += 1;
        if (this.i >= this.s.length) this.fail('Unterminated string starting at', start);
        const e = this.s[this.i] as string;
        if (e === 'u') {
          const hex = this.s.slice(this.i + 1, this.i + 5);
          // CPython reports the offset of the `u` itself, not of the digits.
          //
          // Deliberate narrowing: CPython's test is
          // `len(esc) == 4 and esc[1] not in 'xX'` followed by `int(esc, 16)`,
          // and Python's int() also accepts a sign, surrounding whitespace and
          // digit-separating underscores — so CPython really does accept
          // `\u+123`. Reproducing that is not worth the code; no client emits
          // it, and the failure mode is a 422 either way.
          if (hex.length < 4 || !/^[0-9a-fA-F]{4}$/.test(hex)) {
            this.fail('Invalid \\uXXXX escape', this.i);
          }
          out += String.fromCharCode(parseInt(hex, 16));
          this.i += 5;
          continue;
        }
        const mapped = ESCAPES[e];
        if (mapped === undefined) this.fail('Invalid \\escape', this.i - 1);
        out += mapped;
        this.i += 1;
        continue;
      }
      // CPython rejects raw control characters below 0x20 in strict mode.
      if (c < ' ') this.fail('Invalid control character at');
      out += c;
      this.i += 1;
    }
  }

  private object(): Record<string, unknown> {
    this.i += 1; // '{'
    const out: Record<string, unknown> = {};
    this.ws();
    if (this.s[this.i] === '}') {
      this.i += 1;
      return out;
    }
    for (;;) {
      this.ws();
      if (this.s[this.i] !== '"') this.fail('Expecting property name enclosed in double quotes');
      const key = this.string();
      this.ws();
      if (this.s[this.i] !== ':') this.fail("Expecting ':' delimiter");
      this.i += 1;
      this.ws();
      // A later duplicate key wins, as in CPython.
      out[key] = this.value();
      this.ws();
      const c = this.s[this.i];
      if (c === '}') {
        this.i += 1;
        return out;
      }
      if (c !== ',') this.fail("Expecting ',' delimiter");
      this.i += 1;
    }
  }

  private array(): unknown[] {
    this.i += 1; // '['
    const out: unknown[] = [];
    this.ws();
    if (this.s[this.i] === ']') {
      this.i += 1;
      return out;
    }
    for (;;) {
      this.ws();
      out.push(this.value());
      this.ws();
      const c = this.s[this.i];
      if (c === ']') {
        this.i += 1;
        return out;
      }
      if (c !== ',') this.fail("Expecting ',' delimiter");
      this.i += 1;
    }
  }
}

/** Throws PyJsonError with CPython's message and offset. */
export function pyJsonLoads(text: string): unknown {
  return new Scanner(text).parse();
}

export interface Issue {
  type: string;
  loc: (string | number)[];
  msg: string;
  input: unknown;
  ctx?: Record<string, unknown>;
  url?: string;
}

/** FastAPI's envelope for an unparseable body. `input` is `{}`, not the text. */
export function jsonInvalidIssue(err: PyJsonError): Issue {
  return {
    type: 'json_invalid',
    loc: ['body', err.pos],
    msg: 'JSON decode error',
    input: {},
    ctx: { error: err.pyMessage },
  };
}

/** `body: dict = Body(...)` with no body at all. */
export function bodyMissingIssue(): Issue {
  return {
    type: 'missing',
    loc: ['body'],
    msg: 'Field required',
    input: null,
    url: 'https://errors.pydantic.dev/2.13/v/missing',
  };
}

/** `body: dict = Body(...)` given valid JSON that is not an object. */
export function bodyNotDictIssue(input: unknown): Issue {
  return {
    type: 'dict_type',
    loc: ['body'],
    msg: 'Input should be a valid dictionary',
    input,
    url: 'https://errors.pydantic.dev/2.13/v/dict_type',
  };
}
