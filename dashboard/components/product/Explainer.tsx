import type { ReactNode } from "react";
import { Modal } from "@/components/product/Modal";

/**
 * A section-length explanation, behind a button.
 *
 * Several pages carry a block like this: a heading, two or three paragraphs of
 * concept, and a reference table of commands — three hundred words explaining a
 * mechanism, permanently open, at the bottom of a page somebody opened to do
 * something else. It is worth reading once. It is not worth re-reading every
 * time, and it pushes the page's actual content off the screen for everyone who
 * already has.
 *
 * So the page keeps one line — the claim itself, which is the part that has to
 * be visible — and this holds the rest.
 *
 * Distinct from InfoTip, which is for a clause: a sentence of context on one
 * word or column heading, in a tooltip. Anything with its own structure — more
 * than one paragraph, or a table — is an Explainer. The dividing line is whether
 * it has structure, not how long it is.
 *
 * Uses the same native <dialog> as every other modal here, so Esc, focus
 * trapping and the backdrop all behave the way they do elsewhere.
 */
export function Explainer({
  label,
  title,
  children,
}: {
  /** The button's text. Says what the reader will learn, not "More info". */
  label: string;
  /** The dialog's heading. Usually the section heading this replaced. */
  title: string;
  children: ReactNode;
}) {
  return (
    <Modal trigger={label} triggerClassName="explainer-btn" title={title}>
      <div className="explainer">{children}</div>
    </Modal>
  );
}
