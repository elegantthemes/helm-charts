
const url = process.env.SESSION_RUNNER_URL + '/sessions/' + process.env.SESSION_ID + '/activation';
(async () => {
  while (Date.now() < Number(process.env.SESSION_STARTUP_DEADLINE)) {
    try {
      const r = await fetch(url, {method:'POST', signal:AbortSignal.timeout(15000),
        headers:{authorization:'Bearer '+process.env.SESSION_TOKEN,'content-type':'application/json'},
        body:JSON.stringify({uid:process.env.POD_UID,generation:Number(process.env.EXECUTION_GENERATION)})});
      const result = r.ok ? await r.json() : undefined;
      if (result?.activated === true && result.uid === process.env.POD_UID &&
          result.generation === Number(process.env.EXECUTION_GENERATION)) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve,1000));
  }
  process.exitCode = 1;
})();