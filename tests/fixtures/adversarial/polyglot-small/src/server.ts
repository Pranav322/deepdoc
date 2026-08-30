// File: server.ts - TypeScript Express API
// Part of the polyglot-small fixture: supported language, should be fully parsed.

import express from 'express';

const app = express();

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok' });
});

app.listen(3000, () => {
  console.log('Server running on port 3000');
});