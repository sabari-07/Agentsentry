interface Props {
  diff: string;
}

/** Renders a cdk diff with +/- lines colorized. */
export function CdkDiff({ diff }: Props) {
  const lines = diff.split("\n");
  return (
    <pre className="code">
      {lines.map((line, i) => {
        const trimmed = line.trimStart();
        let cls = "ctx";
        if (trimmed.startsWith("[+]") || trimmed.startsWith("+")) cls = "add";
        else if (trimmed.startsWith("[-]") || trimmed.startsWith("-")) cls = "del";
        return (
          <span key={i} className={cls}>
            {line}
            {i < lines.length - 1 ? "\n" : ""}
          </span>
        );
      })}
    </pre>
  );
}
