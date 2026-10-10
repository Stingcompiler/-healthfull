/**
 * The fast path of `fixture()`: one long-running `manage.py e2e_fixture --serve` per
 * Playwright worker instead of one `manage.py` process per call (e2e/README.md).
 *
 * Starting Python and Django and importing every app costs seconds per call; the fixture
 * itself is usually a few hundred milliseconds. The server pays the start once and then answers
 * JSON requests over stdin/stdout, one line each, strictly in order. Each fixture still runs in
 * its own transaction through the same builders, so specs see exactly the data a separate
 * process would have made.
 *
 * The server is started on the first call and ends when the worker ends (its stdin closes). A
 * server that dies or stops answering is killed; the calls waiting on it fail and the next call
 * starts a new one. `E2E_FIXTURE_MODE=process` turns the fast path off (one process per call,
 * as before), which is how the before/after timings were measured.
 */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

export interface ServerAnswer {
  id: number;
  ok: boolean;
  fixture?: string;
  result?: unknown;
  results?: ServerAnswer[];
  error?: { code: string; message: string; details: Record<string, unknown> };
  crash?: string;
  traceback?: string;
}

interface Waiting {
  id: number;
  resolve: (answer: ServerAnswer) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

/** Per request; a paid visit takes well under a second once the server runs. */
const REQUEST_TIMEOUT_MS = 120_000;

export interface ServerLaunch {
  command: string;
  args: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
}

export class FixtureServer {
  private child: ChildProcessWithoutNullStreams | undefined;
  private waiting: Waiting[] = [];
  private nextId = 1;
  private stderrTail = "";

  constructor(private readonly launch: () => ServerLaunch) {}

  /** Send one request (`{name, params}` or `{batch}`) and wait for its answer. */
  request(body: Record<string, unknown>): Promise<ServerAnswer> {
    const child = this.ensure();
    const id = this.nextId++;
    return new Promise<ServerAnswer>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.fail(
          new Error(`e2e_fixture server: no answer to request ${String(id)} in ${String(REQUEST_TIMEOUT_MS)} ms`),
        );
      }, REQUEST_TIMEOUT_MS);
      this.waiting.push({ id, resolve, reject, timer });
      child.stdin.write(`${JSON.stringify({ ...body, id })}\n`);
    });
  }

  /** Stop the server (the next request starts a new one). */
  stop(): void {
    this.fail(new Error("e2e_fixture server stopped"));
  }

  private ensure(): ChildProcessWithoutNullStreams {
    if (this.child && this.child.exitCode === null && !this.child.killed) return this.child;
    const { command, args, cwd, env } = this.launch();
    const child = spawn(command, args, { cwd, env, stdio: ["pipe", "pipe", "pipe"] });
    this.child = child;
    this.stderrTail = "";
    createInterface({ input: child.stdout }).on("line", (line) => this.onLine(line));
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      this.stderrTail = (this.stderrTail + chunk).slice(-4000);
    });
    child.on("exit", (code, signal) => {
      if (this.child === child) {
        this.child = undefined;
        this.rejectAll(
          new Error(`e2e_fixture server exited (code ${String(code)}, signal ${String(signal)})\n${this.stderrTail}`),
        );
      }
    });
    child.on("error", (error) => {
      if (this.child === child) this.fail(error);
    });
    // Never keep a finished worker alive: the server ends when its stdin closes.
    child.unref();
    for (const stream of [child.stdin, child.stdout, child.stderr]) {
      (stream as unknown as { unref?: () => void }).unref?.();
    }
    return child;
  }

  private onLine(line: string): void {
    if (!line.trim()) return;
    let answer: ServerAnswer;
    try {
      answer = JSON.parse(line) as ServerAnswer;
    } catch {
      this.fail(new Error(`e2e_fixture server wrote something that is not JSON: ${line.slice(0, 500)}`));
      return;
    }
    const head = this.waiting.shift();
    if (!head) return;
    clearTimeout(head.timer);
    if (answer.id !== head.id) {
      head.reject(new Error(`e2e_fixture server answered request ${String(answer.id)}, expected ${String(head.id)}`));
      this.fail(new Error("e2e_fixture server answers out of order"));
      return;
    }
    head.resolve(answer);
  }

  private rejectAll(error: Error): void {
    const waiting = this.waiting;
    this.waiting = [];
    for (const w of waiting) {
      clearTimeout(w.timer);
      w.reject(error);
    }
  }

  private fail(error: Error): void {
    const child = this.child;
    this.child = undefined;
    if (child && child.exitCode === null) child.kill("SIGKILL");
    this.rejectAll(error);
  }
}
