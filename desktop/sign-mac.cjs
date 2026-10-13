'use strict';
const {signAsync} = require('@electron/osx-sign');
const path = require('node:path');
const fs = require('node:fs');
const app = path.resolve(process.argv[2] || '');
const identity = process.env.GRID_SIGN_IDENTITY;
if (!identity || !identity.startsWith('Developer ID Application:')) {
  throw new Error('GRID_SIGN_IDENTITY must name a Developer ID Application certificate.');
}
if (!fs.existsSync(path.join(app, 'Contents', 'Info.plist'))) throw new Error('App bundle missing');
signAsync({app, identity, platform:'darwin', type:'distribution',
  binaries:[path.join(app,'Contents','Resources','engine','uv')],
  optionsForFile: () => ({hardenedRuntime:true}),
}).catch(error => {console.error(error.message); process.exitCode=1;});
