/** Profile text sometimes uses " -- " as a dash. Show it as normal sentence punctuation instead. */
export function tidyText(text: string): string {
  return text.replace(/\s--\s+(\S)/g, (_match, c: string) => `. ${c.toUpperCase()}`);
}
