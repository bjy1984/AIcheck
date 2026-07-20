export function createSingleFlight(run, keyFor = () => "default") {
  if (typeof run !== "function") {
    throw new TypeError("single-flight runner must be a function");
  }
  if (typeof keyFor !== "function") {
    throw new TypeError("single-flight key function must be a function");
  }

  const active = new Map();

  return function runSingleFlight(...args) {
    const key = String(keyFor(...args));
    const existing = active.get(key);
    if (existing) return existing.promise;

    const record = {};
    record.promise = Promise.resolve()
      .then(() => run(...args))
      .finally(() => {
        if (active.get(key) === record) active.delete(key);
      });
    active.set(key, record);
    return record.promise;
  };
}
