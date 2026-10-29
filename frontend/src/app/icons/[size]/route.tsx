import { appIcon } from "@/lib/icon";

const SIZES = [192, 512];

export const dynamic = "force-static";

export function generateStaticParams() {
  return SIZES.map((size) => ({ size: String(size) }));
}

export async function GET(_: Request, { params }: { params: Promise<{ size: string }> }) {
  const size = Number((await params).size);
  if (!SIZES.includes(size)) return new Response("Not found", { status: 404 });
  return appIcon(size);
}
