// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Generates src/protocol/messages.ts from src/protocol/protocol.schema.json, which is itself
 * generated from agent/protocol.py (`python -m agent.protocol`). Run with `npm run gen:protocol`.
 *
 * Writes the message types, plus AUDIO_FORMAT as a runtime value: the schema pins each of its
 * fields to a single `const`, which TypeScript types alone can't hand to an AudioContext.
 */

import { readFile, writeFile } from 'node:fs/promises';
import { compile } from 'json-schema-to-typescript';

const dir = new URL('../src/protocol/', import.meta.url);
const schema = JSON.parse(await readFile(new URL('protocol.schema.json', dir), 'utf8'));

const banner = `// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

// Generated from agent/protocol.py: run \`python -m agent.protocol\`, then \`npm run gen:protocol\`.
// Do not edit by hand.`;

const options = {
  additionalProperties: false,
  format: true,
  style: { singleQuote: true, printWidth: 110 },
};
const messages = await compile(schema, 'ServerMessage', { ...options, bannerComment: banner });

// No message refers to AudioFormat (it describes the binary frames), so compile it on its own.
const audioSchema = schema.$defs.AudioFormat;
const audioType = await compile(audioSchema, 'AudioFormat', { ...options, bannerComment: '' });
const audioFormat = Object.entries(audioSchema.properties).map(([name, field]) => {
  if (!('const' in field)) throw new Error(`AudioFormat.${name} has no const value`);
  return `  ${name}: ${JSON.stringify(field.const).replaceAll('"', "'")},`;
});
const constants = `
/** The format of every binary frame, in both directions. */
export const AUDIO_FORMAT = {
${audioFormat.join('\n')}
} as const satisfies AudioFormat;
`;

await writeFile(new URL('messages.ts', dir), `${messages}\n${audioType}${constants}`);
console.error('wrote src/protocol/messages.ts');
