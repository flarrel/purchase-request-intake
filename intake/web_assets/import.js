const upload = document.querySelector("#file");
const contents = document.querySelector("#csv");
if (upload && contents) {
  upload.addEventListener("change", async () => {
    const file = upload.files[0];
    if (!file) return;
    if (file.size > 256000) {
      upload.setCustomValidity("Choose a CSV under 256 kB.");
      upload.reportValidity();
      return;
    }
    upload.setCustomValidity("");
    contents.value = await file.text();
    contents.focus();
  });
}
