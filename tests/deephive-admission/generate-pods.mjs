// Offline fixture generation from a participating DeepHive checkout. Node 24+.
// Only the unused object-storage dependency of retainedArtifacts is stubbed.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
const source = resolve(process.argv[2]);
const modules = new Map();
async function load(file) {
  if (modules.has(file)) return modules.get(file);
  const module = new vm.SourceTextModule(stripTypeScriptTypes(readFileSync(file, 'utf8')), {identifier: pathToFileURL(file).href});
  modules.set(file, module);
  await module.link(async (specifier, parent) => {
    if (specifier === '../evidence.js') {
      // sessionPod calls only evidenceSubPath, never these exports.
      return new vm.SyntheticModule(['sanitizeEvidenceText', 'EvidenceStorageError'], function () {
        this.setExport('sanitizeEvidenceText', () => { throw Error('Unexpected evidence call'); });
        this.setExport('EvidenceStorageError', Error);
      });
    }
    if (specifier.startsWith('node:')) {
      const native = await import(specifier);
      return new vm.SyntheticModule(Object.keys(native), function () {
        for (const key of Object.keys(native)) this.setExport(key, native[key]);
      });
    }
    return load(resolve(dirname(fileURLToPath(parent.identifier)), specifier.replace(/\.js$/, '.ts')));
  });
  return module;
}
const module = await load(resolve(source, 'src/task-environments/environment/pod.ts'));
await module.evaluate();
const root = dirname(fileURLToPath(import.meta.url));
const values = JSON.parse(readFileSync(resolve(root, 'values.json'))).fullWorker;
const session = {id: 'dh-' + 'a'.repeat(40), taskId: 'fixture-task', image: values.sessionImage,
  owner: {generation: 1, executionGeneration: 1}, createdAt: 1000, startupDeadline: 12345};
const config = {namespace: 'dph-app', release: 'review', nodeName: values.nodeName,
  imagePullSecret: values.pullSecret, workspaceClaim: values.workspaceClaim,
  sourceSubPath: 'tasks/fixture', agentSecret: values.agentSecret, integrationSecret: values.integrationSecret,
  databaseImage: values.databaseImage, dependencyMounts: [],
  runnerUrl: 'http://review-full-worker:3001', sessionToken: 'fixture'};
for (const protocol of [2, 3, 4]) {
  const pod = module.namespace.sessionPod({...session, protocol}, config);
  // Kubernetes default, applied identically to all fixtures.
  pod.spec.serviceAccountName = 'default';
  writeFileSync(resolve(root, `pod-protocol${protocol}.json`), JSON.stringify(pod, null, 2) + '\n');
}
