import { loadType, countForType } from "@/lib/loadData";

export default async function HomePage() {
  // Load video count as an example
  const videoCount = await countForType("videos");

  return (
    <main style={{ maxWidth: 800, margin: "0 auto", padding: "2rem" }}>
      <h1>Welcome</h1>
      <p>
        This site is powered by{" "}
        <a href="https://github.com/yazin/yt-to-site" target="_blank" rel="noopener">
          yt-to-site
        </a>
        .
      </p>
      <p>Videos: {videoCount}</p>

      <h2>Recent Videos</h2>
      <VideoList />
    </main>
  );
}

async function VideoList() {
  const videos = await loadType("videos");
  const recent = videos.slice(0, 20);

  if (recent.length === 0) {
    return <p>No videos yet. Run the pipeline to fetch content.</p>;
  }

  return (
    <ul>
      {recent.map((video) => (
        <li key={String(video.id)} style={{ marginBottom: "0.5rem" }}>
          <strong>{video.title || video.full_title}</strong>
          {video.authored_date && (
            <span style={{ color: "#666", marginLeft: "0.5rem" }}>
              {new Date(video.authored_date).toLocaleDateString()}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
