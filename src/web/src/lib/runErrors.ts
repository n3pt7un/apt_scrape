/** Turn the runner's raw error line (Playwright, network, Notion) into a cause and a fix in plain Italian. */
export function explainRunError(raw: string | null | undefined): { title: string; fix: string } {
  const s = raw ?? ''
  if (/^Run timed out after/i.test(s))
    return {
      title: 'La run ha superato il tempo massimo',
      fix: 'Questa ricerca ha un limite di durata: riduci le pagine da leggere o alza il limite nella configurazione. Gli annunci già raccolti sono salvati.',
    }
  if (/^Run (cancelled|interrupted)/i.test(s))
    return {
      title: 'Run interrotta: il backend si è fermato',
      fix: 'Il backend è stato chiuso o riavviato durante la run. Rilanciala: la nuova run rilegge solo quello che manca.',
    }
  if (/timeout \d+ms exceeded|timed? ?out/i.test(s))
    return {
      title: 'Il portale non ha risposto in tempo',
      fix: 'Capita quando il sito è lento o sta rallentando le richieste. Riprova tra qualche minuto; se si ripete, attiva la rotazione VPN o allunga le pause tra le pagine.',
    }
  if (/\b(403|429)\b|captcha|blocked|access denied|forbidden|too many requests/i.test(s))
    return {
      title: 'Il portale ha bloccato la richiesta',
      fix: 'Riprova più tardi con la rotazione VPN attiva e pause più lunghe tra le pagine.',
    }
  if (/proxy|socks|nordvpn/i.test(s))
    return {
      title: 'La connessione VPN non ha funzionato',
      fix: 'Controlla le credenziali NordVPN nel file .env, oppure disattiva la rotazione VPN per questa ricerca.',
    }
  if (/net::ERR|ENOTFOUND|ECONNREFUSED|ECONNRESET|getaddrinfo|name or service not known/i.test(s))
    return {
      title: 'Connessione assente o interrotta',
      fix: 'Controlla la rete del computer e riprova.',
    }
  if (/notion/i.test(s))
    return {
      title: 'Invio a Notion non riuscito',
      fix: 'Controlla la chiave e il database Notion nel file .env.',
    }
  return {
    title: 'Errore imprevisto durante la run',
    fix: 'Il log qui sotto mostra dove si è fermata. Riprova; se si ripete, il dettaglio tecnico aiuta a capire il perché.',
  }
}
