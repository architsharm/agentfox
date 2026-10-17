import Image from "next/image";
import Link from "next/link";

import { blogPath, formatDate, type BlogPost } from "@/lib/marketing/blog";

/** A post on the index and in "Keep reading": the cover, the topic, the claim. */
export function PostCard({ post, featured = false }: { post: BlogPost; featured?: boolean }) {
  return (
    <Link href={blogPath(post.slug)} className={featured ? "blog-card blog-card-featured" : "blog-card"}>
      <div className="blog-card-img">
        <Image
          src={post.image.src}
          alt=""
          width={post.image.width}
          height={post.image.height}
          sizes={featured ? "(max-width: 900px) 100vw, 640px" : "(max-width: 900px) 100vw, 360px"}
        />
      </div>
      <div className="blog-card-body">
        <span className="mk-chip mk-chip-accent">{post.tag}</span>
        {featured ? <h2>{post.title}</h2> : <h3>{post.title}</h3>}
        <p>{post.description}</p>
        <span className="blog-card-meta">
          <time dateTime={post.published}>{formatDate(post.published)}</time> · {post.readMinutes} min read
        </span>
      </div>
    </Link>
  );
}
