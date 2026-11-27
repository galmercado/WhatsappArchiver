export default function setup(): void {
  process.env.TZ = "UTC"; // deterministic date formatting in tests
}
