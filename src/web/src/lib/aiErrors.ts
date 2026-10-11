/** Turn a raw provider error into the problem and the fix, in plain Italian. */
export function explainAiError(raw: string | null | undefined): { title: string; fix: string } {
  const s = (raw ?? '').toLowerCase()
  if (/401|authenticat|invalid x-api-key|api key|unauthori/.test(s))
    return { title: 'Chiave AI non valida o scaduta', fix: 'Controlla la chiave nel file .env (ANTHROPIC_API_KEY o OPENROUTER_API_KEY), riavvia il backend, poi premi Valuta adesso.' }
  if (/404|not_found|model:/.test(s))
    return { title: 'Modello AI inesistente', fix: 'Controlla ANTHROPIC_MODEL nel file .env (es. claude-sonnet-5-5), riavvia il backend e riprova.' }
  if (/429|rate.?limit|quota|overloaded|529/.test(s))
    return { title: 'Servizio AI occupato o quota esaurita', fix: 'Riprova tra qualche minuto.' }
  if (/timeout|timed out|connect|network|unreachable/.test(s))
    return { title: 'Il servizio AI non ha risposto', fix: 'Controlla la connessione e riprova.' }
  if (/preferences|preferenze/.test(s))
    return { title: 'Criteri mancanti', fix: 'Scrivi i tuoi criteri nella pagina Criteri, poi riprova.' }
  return { title: 'Risposta dell’AI illeggibile', fix: 'Riprova: di solito basta una seconda valutazione.' }
}
