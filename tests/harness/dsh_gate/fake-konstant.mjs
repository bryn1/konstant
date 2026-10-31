#!/usr/bin/env node
// A scripted stand-in for bin/konstant (plugin tests): each call logs its argv and stdin to
// $FAKE_K_LOG and answers with the next scripted reply for its verb from $FAKE_K_STATE
// ({"gate": [{code, stdout, stderr}], "check": [...], "close": [...]}); no reply left = exit 99.
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs'
const argv = process.argv.slice(2)
const verb = argv[1] ?? '?'
let stdin = ''
try { stdin = readFileSync(0, 'utf8') } catch { stdin = '' }
appendFileSync(process.env.FAKE_K_LOG, JSON.stringify({ argv, stdin, home: process.env.KONSTANT_HOME, inTask: process.env.KONSTANT_IN_TASK ?? null }) + '\n')
const state = JSON.parse(readFileSync(process.env.FAKE_K_STATE, 'utf8'))
const reply = (state[verb] ?? []).shift()
writeFileSync(process.env.FAKE_K_STATE, JSON.stringify(state))
if (!reply) { process.stderr.write(`fake-konstant: no scripted reply for ${verb}\n`); process.exit(99) }
if (reply.stdout) process.stdout.write(reply.stdout)
if (reply.stderr) process.stderr.write(reply.stderr)
process.exit(reply.code ?? 0)
