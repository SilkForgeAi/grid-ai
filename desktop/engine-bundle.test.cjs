"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { selectEngineWheel } = require("./engine-bundle.cjs");

test("accepts exactly one canonical wheel", () => {
  assert.equal(selectEngineWheel(["uv", "func_timeout-4.3.5-py3-none-any.whl", "grid_ai-0.2.0-py3-none-any.whl"]),
    "grid_ai-0.2.0-py3-none-any.whl");
  assert.equal(selectEngineWheel(["uv"]), null);
});
test("rejects stale sync copies and conflicting versions", () => {
  assert.throws(() => selectEngineWheel(["grid_ai-0.2.0-py3-none-any.whl", "grid_ai-0.2.0-py3-none-any 2.whl"]));
  assert.throws(() => selectEngineWheel(["grid_ai-0.2.0-py3-none-any 2.whl"]));
  assert.throws(() => selectEngineWheel(["grid_ai-0.2.0-py3-none-any.whl", "grid_ai-0.1.0-py3-none-any.whl"]));
});
test("packaging excludes engine resources without dropping the startup helper", () => {
  const manifest = require('./package.json');
  for (const script of ['package:mac', 'package:mac-intel']) {
    assert.match(manifest.scripts[script], /--asar(?: |$)/);
    const pattern = manifest.scripts[script].match(/--ignore='(\^\/engine[^']*)'/)[1];
    const ignored = new RegExp(pattern);
    assert.equal(ignored.test('/engine/grid_ai-0.2.0.whl'), true);
    assert.equal(ignored.test('/engine-bundle.cjs'), false);
  }
});
