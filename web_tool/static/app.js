async function checkHealth() {
  const label = document.querySelector("#runtime-label");
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("health failed");
    label.textContent = "Runtime sẵn sàng";
  } catch {
    label.textContent = "Runtime lỗi";
    document.querySelector(".runtime-status").classList.add("error");
  }
}

checkHealth();

