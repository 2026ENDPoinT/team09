import assert from "node:assert/strict";
import { setTimeout as pause } from "node:timers/promises";
import test from "node:test";
import { createAstraLogin } from "../dist-desktop/desktop/astra-login.js";
import { ScreenData } from "../dist-desktop/desktop/screen-data.js";

const fixtureError = { status: "error", message: "No fixture dataset" };

function fixture(request, requireAccount = false) {
  const calls = [];
  const states = [];
  const bridge = async (name, args) => {
    calls.push([name, args]);
    return request(name, args) ?? fixtureError;
  };
  const data = new ScreenData(bridge, () => login.sessionChanged());
  const login = createAstraLogin(data, bridge, (state) => states.push(state.state), requireAccount);
  return { login, data, states, calls, stop() { login.shutdown(); data.shutdown(); } };
}

test("startup verifies the saved account before enabling private reads without opening a browser", async (t) => {
  const account = "a".repeat(64);
  let finish;
  const verification = new Promise((resolve) => { finish = resolve; });
  const { login, data, calls, stop } = fixture((name) => name === "confirm_desktop_login" ? verification : undefined, true);
  t.after(stop);
  const startup = login.initialize(async () => ({ keepLogin: true }));
  assert.equal(login.snapshot().state, "verifying");
  assert.equal(data.confirmedSessionRevision, undefined);
  const click = login.start();
  finish({ status: "authenticated", message: "verified", account_key: account });
  await startup;
  assert.equal((await click).state, "authenticated");
  assert.equal(data.account.key, account);
  assert.deepEqual(calls.filter(([name]) => name.includes("login")), [["confirm_desktop_login", {}]]);
});

test("an expired saved session leaves the app at the normal login screen", async (t) => {
  const { login, calls, stop } = fixture((name) => {
    if (name === "confirm_desktop_login") return { status: "login_required", message: "expired" };
    if (name === "start_desktop_login") return { status: "opened", message: "opened" };
  });
  t.after(stop);
  await login.initialize(async () => ({ keepLogin: true }));
  assert.equal(login.snapshot().state, "idle");
  assert.deepEqual(calls, [["confirm_desktop_login", {}]]);
  assert.equal((await login.start()).state, "waiting");
});

test("fresh login mode clears saved sessions before allowing manual login and retries failed cleanup", async (t) => {
  let clears = 0;
  const { login, calls, stop } = fixture((name) => {
    if (name === "clear_desktop_login") return ++clears === 1 ? fixtureError : { status: "cleared" };
    if (name === "start_desktop_login") return { status: "opened", message: "opened" };
  });
  t.after(stop);
  await login.initialize(async () => ({ keepLogin: false }));
  assert.equal(login.snapshot().state, "error");
  assert.equal((await login.start()).state, "waiting");
  assert.deepEqual(calls, [["clear_desktop_login", {}], ["clear_desktop_login", {}], ["start_desktop_login", {}]]);
});

async function waitFor(predicate) {
  const until = Date.now() + 3000;
  while (Date.now() < until) {
    if (predicate()) return;
    await pause(25);
  }
  assert.fail("login state did not arrive");
}

test("automatic browser capture verifies fresh login exactly once and starts prefetch", async (t) => {
  let finishVerification;
  const verification = new Promise((resolve) => { finishVerification = resolve; });
  const { login, data, states, calls, stop } = fixture((name) => {
    if (name === "start_desktop_login") return { status: "opened", message: "opened" };
    if (name === "get_desktop_login_status") return { status: "captured", message: "captured" };
    if (name === "confirm_desktop_login") return verification;
  });
  t.after(stop);
  assert.equal((await login.start()).state, "waiting");
  await waitFor(() => login.snapshot().state === "verifying");
  assert.equal(data.confirmedSessionRevision, undefined);
  assert.equal((await data.overview()).status, "login_required");
  const secondClick = login.start();
  finishVerification({ status: "authenticated", message: "verified" });
  assert.equal((await secondClick).state, "authenticated");
  assert.equal(typeof data.confirmedSessionRevision, "number");
  assert.notEqual(data.status.state, "idle");
  assert.deepEqual(states, ["opening", "waiting", "verifying", "authenticated"]);
  assert.deepEqual(calls.slice(0, 3), [
    ["start_desktop_login", {}], ["get_desktop_login_status", {}], ["confirm_desktop_login", { use_saved: false }],
  ]);
  assert.equal(calls.filter(([name]) => name === "confirm_desktop_login").length, 1);
});

test("the same button rechecks the pending browser and reopens only if it was closed", async (t) => {
  let capture = "pending";
  const { login, calls, stop } = fixture((name) => {
    if (name === "start_desktop_login") return { status: "opened", message: "opened" };
    if (name === "get_desktop_login_status") return { status: capture, message: capture };
    if (name === "confirm_desktop_login") return { status: "authenticated", message: "verified" };
  });
  t.after(stop);
  await login.start();
  assert.equal((await login.start()).state, "waiting");
  assert.deepEqual(calls, [["start_desktop_login", {}], ["get_desktop_login_status", { recheck: true }]]);
  capture = "closed";
  assert.equal((await login.start()).state, "waiting");
  assert.equal(calls.filter(([name]) => name === "start_desktop_login").length, 2);
  capture = "captured";
  assert.equal((await login.start()).state, "authenticated");
});

test("a captured login can retry verification after a network failure", async (t) => {
  let verifications = 0;
  const { login, calls, stop } = fixture((name) => {
    if (name === "start_desktop_login") return { status: "opened", message: "opened" };
    if (name === "get_desktop_login_status") return { status: "captured", message: "captured" };
    if (name === "confirm_desktop_login") return ++verifications === 1 ? fixtureError : { status: "authenticated", message: "verified" };
  });
  t.after(stop);
  await login.start();
  assert.equal((await login.start()).state, "error");
  assert.equal((await login.start()).state, "authenticated");
  assert.equal(calls.filter(([name]) => name === "start_desktop_login").length, 1);
  assert.equal(verifications, 2);
});
