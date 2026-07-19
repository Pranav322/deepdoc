'use strict';

// Simple async queue — max 2 concurrent jobs (next build is RAM-heavy).
const MAX_CONCURRENT = 2;
let running = 0;
const pending = [];

function enqueue(task) {
  return new Promise((resolve, reject) => {
    pending.push({ task, resolve, reject });
    drain();
  });
}

function drain() {
  while (running < MAX_CONCURRENT && pending.length > 0) {
    const { task, resolve, reject } = pending.shift();
    running++;
    task()
      .then(resolve)
      .catch(reject)
      .finally(() => {
        running--;
        drain();
      });
  }
}

function queueDepth() {
  return { running, pending: pending.length };
}

module.exports = { enqueue, queueDepth };
