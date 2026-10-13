"use strict";

function selectEngineWheel(files) {
  const wheels = files.filter((name) => /^grid_ai-.+\.whl$/.test(name));
  if (!wheels.length) return null;
  if (wheels.length !== 1 || !/^grid_ai-[A-Za-z0-9_.+-]+\.whl$/.test(wheels[0])) {
    throw new Error("The engine bundle contains conflicting wheels. Reinstall a clean Grid build.");
  }
  return wheels[0];
}

module.exports = { selectEngineWheel };
