import esbuild from 'esbuild';
import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

console.log('Bundling metrics_chart_test_suite.jsx with esbuild...');

const entryFile = path.resolve(__dirname, 'metrics_chart_test_suite.jsx');
const distFile = path.resolve(__dirname, 'dist_test_suite.mjs');

try {
  esbuild.buildSync({
    entryPoints: [entryFile],
    bundle: true,
    format: 'esm',
    platform: 'node',
    jsx: 'automatic',
    external: [
      'react',
      'react/jsx-runtime',
      'react-dom',
      'react-dom/server',
      'lucide-react',
      'recharts',
      '@tanstack/react-query',
    ],
    outfile: distFile,
  });
  console.log(`Bundle complete: ${distFile}`);
} catch (err) {
  console.error('Failed to bundle test suite:', err);
  process.exit(1);
}

const child = spawn(process.execPath, [distFile], { stdio: 'inherit' });
child.on('close', (code) => {
  process.exit(code);
});

