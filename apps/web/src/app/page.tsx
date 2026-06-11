const stats = [
  { label: "Solde", value: "—", hint: "Compte démo OANDA" },
  { label: "Profit journalier", value: "—", hint: "En attente du moteur" },
  { label: "Drawdown", value: "—", hint: "Max 3 % / jour" },
  { label: "Taux de réussite", value: "—", hint: "Aucun trade encore" },
];

export default function Home() {
  return (
    <div className="flex flex-1 flex-col bg-zinc-50 font-sans dark:bg-zinc-950">
      <header className="border-b border-zinc-200 bg-white px-8 py-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            <span className="text-amber-500">Nexa</span>Gold
          </h1>
          <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-600 dark:text-amber-400">
            Paper trading · XAU/USD
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-8 py-10">
        <h2 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Tableau de bord
        </h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Le moteur n&apos;est pas encore connecté — les données apparaîtront
          ici dès la première session de paper trading.
        </p>

        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900"
            >
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                {stat.label}
              </p>
              <p className="mt-2 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
                {stat.value}
              </p>
              <p className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">
                {stat.hint}
              </p>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
