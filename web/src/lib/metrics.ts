const HERO = ['train/loss', 'loss', 'train_loss', 'eval/loss', 'val/loss', 'val_loss', 'rollout/ep_return', 'reward', 'return']

/** The metric a project leads with when the viewer hasn't picked one. */
export function pickHero(names: Iterable<string>): string | null {
  const all = [...names]
  if (!all.length) return null
  for (const h of HERO) if (all.includes(h)) return h
  return all.find((n) => /loss/i.test(n)) ?? all.sort()[0]
}

/** -1 when lower is better, 1 when higher is better, 0 when unknown. */
export function direction(name: string): -1 | 0 | 1 {
  const n = name.toLowerCase()
  if (/loss|error|err\b|perplexity|ppl|mse|mae|rmse|regret|kl\b|nll|cer|wer/.test(n)) return -1
  if (/acc|return|reward|score|f1|auc|precision|recall|bleu|rouge|win|success|map\b|iou/.test(n)) return 1
  return 0
}

export function splitName(name: string): { group: string; leaf: string } {
  const i = name.indexOf('/')
  return i < 0 ? { group: '', leaf: name } : { group: name.slice(0, i), leaf: name.slice(i + 1) }
}

/** Metrics grouped by prefix, groups in a stable, sensible order. */
export function groups(names: string[]): { group: string; metrics: string[] }[] {
  const by = new Map<string, string[]>()
  for (const n of names) {
    const { group } = splitName(n)
    if (!by.has(group)) by.set(group, [])
    by.get(group)!.push(n)
  }
  const rank = (g: string) => {
    const order = ['train', 'eval', 'val', 'valid', 'test', 'rollout', '', 'optim', 'throughput', 'sys', 'system']
    const i = order.indexOf(g)
    return i < 0 ? 5.5 : i
  }
  return [...by]
    .map(([group, metrics]) => ({ group, metrics: metrics.sort() }))
    .sort((a, b) => rank(a.group) - rank(b.group) || a.group.localeCompare(b.group))
}
