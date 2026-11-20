import { ui } from "./ui";

/** Text with bare URLs turned into links, Markdown bold and italics markers removed. */
export default function Linked({ text }: { text: string }) {
  return (
    <>
      {text.split(/(https?:\/\/[^\s),]+)/g).map((part, i) =>
        /^https?:\/\//.test(part) ? (
          <a key={i} href={part} target="_blank" rel="noopener" className={ui.link}>{part}</a>
        ) : (
          part.replace(/\*\*/g, "").replace(/^_(.*)_$/, "$1")
        ),
      )}
    </>
  );
}
