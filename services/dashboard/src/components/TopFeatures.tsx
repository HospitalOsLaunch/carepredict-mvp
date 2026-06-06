interface TopFeaturesProps {
  features: string[];
}

export function TopFeatures({ features }: TopFeaturesProps) {
  return (
    <section className="top-features" aria-label="Variables influentes">
      <h2>Variables influentes</h2>
      <ol>
        {features.slice(0, 3).map((feature) => (
          <li key={feature}>{feature}</li>
        ))}
      </ol>
    </section>
  );
}
