import ConstellationView from "@/components/ConstellationView";

export default async function UserPage({
  params,
}: {
  params: Promise<{ username: string }>;
}) {
  const { username } = await params;
  const decoded = decodeURIComponent(username);
  return <ConstellationView key={decoded} username={decoded} />;
}
