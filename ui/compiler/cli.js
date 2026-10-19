'use strict'

const path = require('path')
const { createRegistry } = require('../registry')
const { compilePage, writeOutput } = require('./index')

const source = process.argv[2]
const outDir = process.argv[3]
if (!source || !outDir) {
  console.error('usage: node ui/compiler/cli.js <page.ui.js> <out-dir>')
  process.exit(1)
}

const page = require(path.resolve(source))
const output = compilePage(page, createRegistry())
writeOutput(output, path.resolve(outDir))
console.log('compiled: ' + path.resolve(outDir))
