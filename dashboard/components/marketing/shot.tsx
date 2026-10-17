import Image from "next/image";

/**
 * A product screenshot, framed.
 *
 * The measurement that produced this component: the reference site carries 77
 * images and this one carried two, neither of them the product. Everything a
 * visitor saw was a diagram we drew in CSS — accurate, and unmistakably the
 * work of a repository rather than a product. A real screen with a real
 * refusal in it does more in one glance than a hand-drawn box does in a
 * paragraph.
 *
 * The frame is doing three jobs. It crops (these are wide captures and the
 * interesting part is rarely the whole thing), it lifts the image off the
 * page with a shadow so the surrounding ground reads as ground, and it hangs
 * a caption underneath so the reader is told what they are looking at rather
 * than left to infer it.
 *
 * `next/image` with explicit dimensions, because every one of these is a 2x
 * capture and shipping a 2800px PNG to a phone to draw it at 380 is the kind
 * of thing that makes a site feel slow for no visible gain.
 */
export function Shot({
  src,
  alt,
  caption,
  width,
  height,
  priority,
  crop,
  className = "",
  sizes = "(max-width: 900px) 100vw, 640px",
}: {
  src: string;
  alt: string;
  caption?: React.ReactNode;
  width: number;
  height: number;
  priority?: boolean;
  /** Trim the capture to the part worth looking at, as a CSS aspect-ratio. */
  crop?: string;
  className?: string;
  sizes?: string;
}) {
  return (
    <figure className={`shot ${className}`}>
      <div className="shot-frame" style={crop ? { aspectRatio: crop } : undefined}>
        <Image
          src={src}
          alt={alt}
          width={width}
          height={height}
          priority={priority}
          sizes={sizes}
        />
      </div>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}
