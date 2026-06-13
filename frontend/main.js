// Safe shadow variables to prevent ReferenceErrors if config.js is not loaded
const _API_URL        = typeof API_URL        !== 'undefined' ? API_URL        : '';
const _RIG_API_URL    = typeof RIG_API_URL    !== 'undefined' ? RIG_API_URL    : '';
const _OPENAI_API_KEY = typeof OPENAI_API_KEY !== 'undefined' ? OPENAI_API_KEY : '';
const _LOCAL_SAVE_URL = typeof LOCAL_SAVE_URL !== 'undefined' ? LOCAL_SAVE_URL : 'http://localhost:8083';

// ─── State ───────────────────────────────────────────────────────────────
let uploadedFile       = null;
let isGenerating       = false;
let generatedImageUrl  = null;
let currentModelFilename = null;
let currentFbxUrl      = null;
let currentTextureUrl  = null;
let currentAnimal      = "animal";
let currentTheme       = "chibi";
let THEMES = {};

document.addEventListener('DOMContentLoaded', () => {

    // ─── DOM references ───────────────────────────────────────────────────────
    const navLinks           = document.querySelectorAll('.nav-links li');
    const titleEl            = document.getElementById('current-view-title');
    const dropZone           = document.getElementById('drop-zone');
    const fileInput          = document.getElementById('file-input');
    const uploadContent      = document.querySelector('.upload-content');
    const imagePreview       = document.getElementById('image-preview');
    const removeBtn          = document.getElementById('remove-btn');
    const generateBtn        = document.getElementById('generate-btn');
    const btnText            = document.querySelector('#generate-btn .btn-text');
    const loader             = document.querySelector('#generate-btn .loader, #loader-3d');
    const progressContainer  = document.getElementById('progress-container');
    const progressFill       = document.getElementById('progress-fill');
    const progressText       = document.getElementById('progress-text');
    const viewportPlaceholder= document.getElementById('viewport-placeholder');
    const splatViewer        = document.getElementById('splat-viewer');
    const viewportControls   = document.getElementById('viewport-controls');
    const downloadGlbBtn     = document.getElementById('download-glb-btn');

    // ─── Navigation ───────────────────────────────────────────────────────────
    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            if (isGenerating) return;
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            titleEl.textContent = 'TRELLIS.2 3D Generation';
        });
    });

    // ─── Tabs ─────────────────────────────────────────────────────────────────
    const tabAi      = document.getElementById('tab-ai');
    const tabUpload  = document.getElementById('tab-upload');
    const aiView     = document.getElementById('ai-view');
    const uploadView = document.getElementById('upload-view');

    function activateTab(active, inactive, showEl, hideEl) {
        active.classList.add('active');
        inactive.classList.remove('active');
        active.style.background   = 'rgba(255,255,255,0.1)';
        inactive.style.background = 'transparent';
        active.style.color        = 'white';
        inactive.style.color      = 'rgba(255,255,255,0.6)';
        showEl.classList.remove('hidden');
        hideEl.classList.add('hidden');
    }
    tabAi.addEventListener('click',     () => {
        if (isGenerating) return;
        activateTab(tabAi,     tabUpload, aiView,     uploadView);
    });
    tabUpload.addEventListener('click', () => {
        if (isGenerating) return;
        activateTab(tabUpload, tabAi,     uploadView, aiView);
    });

    // ─── AI Character Builder ─────────────────────────────────────────────────
    const categorySelect  = document.getElementById('category-select');
    const themeSelect     = document.getElementById('theme-select');
    const animalSelect    = document.getElementById('animal-select');
    const generate2dBtn   = document.getElementById('generate-2d-btn');
    const loader2d        = document.getElementById('loader-2d');
    const step1Prompt     = document.getElementById('step-1-prompt');
    const step2Review     = document.getElementById('step-2-review');
    const preview2dImg    = document.getElementById('preview-2d-img');
    const proceed3dBtn    = document.getElementById('proceed-3d-btn');
    const regenerate2dBtn = document.getElementById('regenerate-2d-btn');
    const back2dBtn       = document.getElementById('back-2d-btn');

    // Asynchronously fetch and populate lists dynamically
    async function initData() {
        try {
            // Fetch animals list
            const animalsRes = await fetch('animals.json');
            if (animalsRes.ok) {
                const animals = await animalsRes.json();
                animalSelect.innerHTML = '<option value="Creature">Random Creature</option>';
                animals.forEach(name => {
                    const opt = document.createElement('option');
                    opt.value = name;
                    opt.textContent = name;
                    animalSelect.appendChild(opt);
                });
            }

            // Fetch themes & categories
            const themesRes = await fetch('themes.json');
            if (themesRes.ok) {
                THEMES = await themesRes.json();
                categorySelect.innerHTML = '<option value="">Select a category</option>';
                for (const [id, cat] of Object.entries(THEMES)) {
                    const opt = document.createElement('option');
                    opt.value       = id;
                    opt.textContent = cat.name;
                    categorySelect.appendChild(opt);
                }
            }
        } catch (e) {
            console.error('Failed to load dynamic data configuration:', e);
            categorySelect.innerHTML = '<option value="">Failed to load categories</option>';
            animalSelect.innerHTML = '<option value="Creature">Random Creature</option>';
        }
    }

    categorySelect.addEventListener('change', (e) => {
        const catId = e.target.value;
        themeSelect.innerHTML = '';
        if (!catId || !THEMES[catId]) {
            themeSelect.innerHTML = '<option value="">First select a category</option>';
            themeSelect.disabled  = true;
            return;
        }

        // Add random theme option as default selection (auto-select option matching prompt script)
        const randOpt = document.createElement('option');
        randOpt.value = 'random';
        randOpt.textContent = '🎲 Random Theme (Auto-select)';
        themeSelect.appendChild(randOpt);

        THEMES[catId].themes.forEach((t, idx) => {
            const opt = document.createElement('option');
            opt.value       = idx;
            opt.textContent = t.name;
            themeSelect.appendChild(opt);
        });
        themeSelect.disabled = false;
    });

    async function generate2D() {
        const catId    = categorySelect.value;
        const themeIdx = themeSelect.value;

        if (!catId || themeIdx === '') {
            alert('Please select a Category first.');
            return;
        }
        if (!_OPENAI_API_KEY) {
            alert('OpenAI API Key not found. Ensure api_key.txt is set and the server was restarted.');
            return;
        }

        generate2dBtn.disabled = true;
        loader2d.classList.remove('hidden');
        generate2dBtn.querySelector('.btn-text').textContent = 'Generating...';

        try {
            const animal = animalSelect.value.trim() || 'Creature';
            currentAnimal = animal;
            
            let theme;
            if (themeIdx === 'random') {
                const themesList = THEMES[catId].themes;
                theme = themesList[Math.floor(Math.random() * themesList.length)];
                console.log('Randomly selected theme:', theme.name);
            } else {
                theme = THEMES[catId].themes[Number(themeIdx)];
            }
            currentTheme = theme.name;

            const prompt =
                `An adorable, ultra-cute 3D humanoid cartoon ${animal} character, standing upright on two legs, ` +
                `designed in a distinct hyper-chibi anime aesthetic. Extreme proportional emphasis on an oversized, ` +
                `giant round head with large expressive eyes, paired with a tiny, small, stylized body. The character ` +
                `is completely empty-handed with open palms, absolutely not holding anything in its hands, keeping both ` +
                `hands completely free and visible. The character is themed as a ${theme.name}, dressed in a ` +
                `stylized outfit using a curated ${theme.palette} color scheme, wearing a prominent ` +
                `${theme.accessory}. Beautiful smooth surfaces, clean outer outlines, vibrant high-contrast ` +
                `professional color combinations. Perfect symmetrical game-ready 3D character asset, relaxed standard ` +
                `A-pose, set against a solid pure black background, isolated professional studio lighting, high-quality ` +
                `detailed 3D rendering, incredibly cute, charming, and cool vinyl toy aesthetic.`;

            const res = await fetch('https://api.openai.com/v1/images/generations', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${_OPENAI_API_KEY}`,
                    'Content-Type':  'application/json',
                },
                body: JSON.stringify({ model: 'gpt-image-2', prompt, n: 1, size: '1024x1024' }),
            });

            if (!res.ok) throw new Error(await res.text());

            const data = await res.json();
            const img  = data.data && data.data[0];
            if (!img) throw new Error('No image data in response');

            generatedImageUrl = img.b64_json
                ? `data:image/png;base64,${img.b64_json}`
                : img.url;

            if (!generatedImageUrl) throw new Error('No image URL or b64_json returned');

            preview2dImg.src = generatedImageUrl;

            // Persist to images_2D/ on disk (fire-and-forget, non-blocking)
            saveImage2D(generatedImageUrl, animal, theme.name, prompt);

            // Auto-download the 2D reference image
            const dlLink = document.createElement('a');
            dlLink.href     = generatedImageUrl;
            dlLink.download = `character_${animal}_${theme.name.replace(/\s+/g, '_')}.png`;
            document.body.appendChild(dlLink);
            dlLink.click();
            document.body.removeChild(dlLink);

            // Advance to step 2
            step1Prompt.classList.add('hidden');
            step2Review.classList.remove('hidden');

        } catch (e) {
            console.error(e);
            alert('Failed to generate 2D image: ' + e.message);
        } finally {
            generate2dBtn.disabled = false;
            loader2d.classList.add('hidden');
            generate2dBtn.querySelector('.btn-text').textContent = 'Generate 2D Design';
        }
    }

    generate2dBtn.addEventListener('click',   generate2D);
    regenerate2dBtn.addEventListener('click', generate2D);
    back2dBtn.addEventListener('click', () => {
        step2Review.classList.add('hidden');
        step1Prompt.classList.remove('hidden');
    });

    // ─── Save 2D image + prompt to local disk (via local save server) ─────────
    async function saveImage2D(imageDataUrl, animal, themeName, prompt) {
        const saveUrl = _LOCAL_SAVE_URL || 'http://localhost:8081';

        // Strip the data-URI prefix to get pure base64
        const b64 = imageDataUrl.startsWith('data:')
            ? imageDataUrl.split(',')[1]
            : imageDataUrl;  // already raw base64 (shouldn't happen)

        try {
            const res = await fetch(`${saveUrl}/save-image`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    animal,
                    theme_name: themeName,
                    prompt,
                    image_b64: b64,
                }),
            });
            if (res.ok) {
                const { slug } = await res.json();
                console.log(`[images_2D] Saved as ${slug}.png + .txt`);
            } else {
                console.warn('[images_2D] Save server returned', res.status);
            }
        } catch (e) {
            // Non-fatal — the user still gets the image; just log.
            console.warn('[images_2D] Could not reach local save server:', e.message);
        }
    }

    // ─── urlToFile helper ─────────────────────────────────────────────────────
    async function urlToFile(url, filename, mimeType) {
        if (url.startsWith('data:')) {
            const [header, b64] = url.split(',');
            const mime = header.match(/:(.*?);/)[1];
            const bstr = atob(b64);
            const u8   = new Uint8Array(bstr.length);
            for (let i = 0; i < bstr.length; i++) u8[i] = bstr.charCodeAt(i);
            return new File([u8], filename, { type: mime || mimeType });
        }
        const buf = await (await fetch(url)).arrayBuffer();
        return new File([buf], filename, { type: mimeType });
    }

    // ─── Proceed to 3D (from AI step 2) ──────────────────────────────────────
    proceed3dBtn.addEventListener('click', async () => {
        if (!generatedImageUrl) return;
        proceed3dBtn.disabled = true;
        proceed3dBtn.querySelector('.btn-text').textContent = 'Preparing Image...';
        try {
            uploadedFile = await urlToFile(generatedImageUrl, 'ai_character.png', 'image/png');
            imagePreview.src = generatedImageUrl;
            imagePreview.classList.remove('hidden');
            removeBtn.classList.remove('hidden');
            uploadContent.classList.add('hidden');
            proceed3dBtn.querySelector('.btn-text').textContent = 'Proceed to 3D Generation';
            await run3DGeneration();
        } catch (e) {
            console.error(e);
            alert('Error sending to 3D generation: ' + e.message);
            proceed3dBtn.disabled = false;
            proceed3dBtn.querySelector('.btn-text').textContent = 'Proceed to 3D Generation';
        }
    });

    // ─── Drag & Drop / Upload ─────────────────────────────────────────────────
    dropZone.addEventListener('click',    () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave',()  => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop',     (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files?.[0]) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change',  (e) => { if (e.target.files?.[0]) handleFile(e.target.files[0]); });
    removeBtn.addEventListener('click',   (e) => { e.stopPropagation(); resetUpload(); });

    function handleFile(file) {
        if (!file.type.match('image.*')) {
            alert('Please select an image file (PNG, JPG, WEBP)');
            return;
        }
        uploadedFile = file;
        const reader = new FileReader();
        reader.onload = (e) => {
            imagePreview.src = e.target.result;
            imagePreview.classList.remove('hidden');
            removeBtn.classList.remove('hidden');
            uploadContent.classList.add('hidden');
            generateBtn.disabled = false;
        };
        reader.readAsDataURL(file);
    }

    function resetUpload() {
        uploadedFile = null;
        fileInput.value = '';
        imagePreview.src = '';
        imagePreview.classList.add('hidden');
        removeBtn.classList.add('hidden');
        uploadContent.classList.remove('hidden');
        if (!isGenerating) generateBtn.disabled = true;
    }

    // ─── Custom image → 3D generation ────────────────────────────────────────
    generateBtn.addEventListener('click', () => {
        if (!uploadedFile) { alert('Please upload an image first.'); return; }
        run3DGeneration();
    });

    async function run3DGeneration() {
        if (!_API_URL) {
            alert('API_URL is not defined. Did you run start.py?');
            return;
        }

        const isAiTab       = !aiView.classList.contains('hidden');
        const activeBtn     = isAiTab ? proceed3dBtn : generateBtn;
        const activeBtnText = activeBtn.querySelector('.btn-text');
        const activeLoader  = activeBtn.querySelector('.loader');

        isGenerating = true;
        generateBtn.disabled = true;
        proceed3dBtn.disabled = true;

        if (activeBtnText)  activeBtnText.classList.add('hidden');
        if (activeLoader)   activeLoader.classList.remove('hidden');

        progressContainer.classList.remove('hidden');
        viewportPlaceholder.classList.remove('hidden');
        splatViewer.classList.add('hidden');
        splatViewer.src = '';
        viewportControls.classList.add('hidden');

        progressFill.style.width  = '10%';
        progressText.textContent  = 'Connecting to backend...';

        try {
            const removeBgCheck = document.getElementById(isAiTab ? 'remove-bg-2d-toggle' : 'remove-bg-toggle');

            let animal = "animal";
            let theme = "custom";
            if (isAiTab) {
                animal = currentAnimal || "animal";
                theme = currentTheme || "chibi";
            } else {
                if (animalSelect && animalSelect.value) {
                    animal = animalSelect.value;
                }
                if (categorySelect && categorySelect.value && themeSelect && themeSelect.value && themeSelect.value !== 'random') {
                    const catId = categorySelect.value;
                    const tIdx = Number(themeSelect.value);
                    if (THEMES[catId] && THEMES[catId].themes[tIdx]) {
                        theme = THEMES[catId].themes[tIdx].name;
                    }
                }
            }

            const formData = new FormData();
            formData.append('image',     uploadedFile, uploadedFile.name);
            formData.append('remove_bg', removeBgCheck ? removeBgCheck.checked : true);
            formData.append('animal',    animal);
            formData.append('theme',     theme);

            progressFill.style.width = '30%';
            progressText.textContent = 'Uploading image to backend...';
            await mockDelay(500);

            const response = await fetch(`${_API_URL}/generate`, { method: 'POST', body: formData });
            if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);

            const { call_id: callId } = await response.json();

            progressFill.style.width = '50%';
            progressText.textContent = 'Processing 3D Model (Takes ~5-7 mins)...';

            let finalAssetUrl = null;
            while (true) {
                await mockDelay(5000);
                const statusRes  = await fetch(`${_API_URL}/status/${callId}`);
                if (!statusRes.ok) throw new Error('Status check failed');
                const statusData = await statusRes.json();

                if (statusData.status === 'success') {
                    finalAssetUrl = statusData.asset_url;
                    currentFbxUrl = statusData.fbx_url ? `${_API_URL}${statusData.fbx_url}` : null;
                    currentTextureUrl = statusData.texture_url ? `${_API_URL}${statusData.texture_url}` : null;
                    break;
                } else if (statusData.status === 'error') {
                    throw new Error(statusData.message || 'Generation failed');
                }
                progressText.textContent += '.';
            }

            progressFill.style.width = '100%';
            progressText.textContent = 'Complete!';
            await mockDelay(400);

            currentModelFilename = finalAssetUrl.split('/').pop(); // e.g. abc123.glb
            console.log('Generated GLB filename:', currentModelFilename);
            console.log('Generated FBX url:', currentFbxUrl);
            console.log('Generated Texture url:', currentTextureUrl);
            showGeneratedModel();

        } catch (error) {
            console.error(error);
            alert('Generation failed: ' + error.message);
            progressText.textContent = 'Error occurred.';
            progressFill.style.background = 'var(--error)';
        } finally {
            isGenerating = false;
            generateBtn.disabled = !uploadedFile;
            proceed3dBtn.disabled = false;
            if (activeBtnText) activeBtnText.classList.remove('hidden');
            if (activeLoader)  activeLoader.classList.add('hidden');
            setTimeout(() => {
                progressContainer.classList.add('hidden');
                progressFill.style.background = 'var(--accent-gradient)';
            }, 2000);
        }
    }

    // ─── Show GLB in viewer ───────────────────────────────────────────────────
    function showGeneratedModel(rigged = false) {
        viewportPlaceholder.classList.add('hidden');
        const viewerUrl = `viewer.html?glb=${encodeURIComponent(currentModelFilename)}${rigged ? '&is_rigged=true' : ''}`;
        splatViewer.src = viewerUrl;
        splatViewer.classList.remove('hidden');
        viewportControls.classList.remove('hidden');
    }

    // ─── Download GLB button ──────────────────────────────────────────────────
    downloadGlbBtn.addEventListener('click', () => {
        if (!currentModelFilename) { alert('No GLB file ready yet.'); return; }
        window.open(`${_API_URL}/download/${currentModelFilename}`, '_blank');
    });

    // ─── Download FBX button ──────────────────────────────────────────────────
    const downloadFbxBtn = document.getElementById('download-fbx-btn');
    if (downloadFbxBtn) {
        downloadFbxBtn.addEventListener('click', async () => {
            if (!currentFbxUrl) { 
                alert('No FBX file ready yet. Make sure generation has completed.'); 
                return; 
            }
            
            const triggerDownload = async (url, defaultName) => {
                try {
                    const response = await fetch(url);
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    const blob = await response.blob();
                    const blobUrl = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = blobUrl;
                    a.download = url.split('/').pop() || defaultName;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
                } catch (e) {
                    console.warn("Blob download failed, opening in new tab:", e);
                    window.open(url, '_blank');
                }
            };
            
            // Disable button during download to show progress
            downloadFbxBtn.disabled = true;
            const origText = downloadFbxBtn.innerHTML;
            downloadFbxBtn.innerHTML = '<span style="font-size:11px;font-weight:bold;">Downloading...</span>';
            
            try {
                console.log('Downloading FBX:', currentFbxUrl);
                await triggerDownload(currentFbxUrl, 'model.fbx');
                
                if (currentTextureUrl) {
                    console.log('Downloading Texture:', currentTextureUrl);
                    await triggerDownload(currentTextureUrl, 'texture.png');
                }
            } catch (err) {
                console.error("Download failed:", err);
            } finally {
                downloadFbxBtn.disabled = false;
                downloadFbxBtn.innerHTML = origText;
            }
        });
    }

    // ─── Auto-Rig button ──────────────────────────────────────────────────────
    const rigBtn = document.getElementById('rig-btn');
    if (rigBtn) {
        rigBtn.addEventListener('click', async () => {
            if (!currentModelFilename) return;

            rigBtn.disabled   = true;
            const origHtml    = rigBtn.innerHTML;
            rigBtn.innerHTML  = '<span style="font-size:13px;font-weight:bold;">Rigging… (~2 mins)</span>';

            try {
                // Fetch the GLB blob from TRELLIS storage
                const glbRes  = await fetch(`${_API_URL}/download/${currentModelFilename}`);
                const glbBlob = await glbRes.blob();

                const formData = new FormData();
                formData.append('file', glbBlob, currentModelFilename);

                const targetApi = _RIG_API_URL || _API_URL;
                const response  = await fetch(`${targetApi}/rig`, { method: 'POST', body: formData });

                if (!response.ok) throw new Error(await response.text());

                const data = await response.json();
                if (data.status === 'success') {
                    currentModelFilename = data.model_url.split('/').pop();
                    showGeneratedModel(true);
                }
            } catch (err) {
                console.error(err);
                alert('Auto-rig failed: ' + err.message);
            } finally {
                rigBtn.disabled  = false;
                rigBtn.innerHTML = origHtml;
            }
        });
    }

    // ─── Clean Output button ──────────────────────────────────────────────────
    const cleanupBtn = document.getElementById('cleanup-btn');
    if (cleanupBtn) {
        cleanupBtn.addEventListener('click', async () => {
            if (!confirm('Delete all generated assets from backend storage?')) return;
            try {
                const res = await fetch(`${_API_URL}/cleanup`, { method: 'DELETE' });
                if (!res.ok) throw new Error('Cleanup failed');
                alert('Storage cleaned successfully.');
                currentModelFilename = null;
                currentFbxUrl = null;
                currentTextureUrl = null;
                viewportPlaceholder.classList.remove('hidden');
                splatViewer.classList.add('hidden');
                viewportControls.classList.add('hidden');
            } catch (err) {
                alert('Failed to clean storage.');
            }
        });
    }

    // ─── Utilities ────────────────────────────────────────────────────────────
    function mockDelay(ms) { return new Promise(r => setTimeout(r, ms)); }

    // ─── Backend status monitor ───────────────────────────────────────────────
    const statusTextEl = document.getElementById('backend-status');
    const pulseDotEl   = document.querySelector('.pulse-dot');

    async function checkBackendStatus() {
        if (!_API_URL) {
            statusTextEl.textContent = 'Backend Offline';
            pulseDotEl.className     = 'pulse-dot error';
            generateBtn.disabled     = true;
            if (btnText) btnText.textContent = 'Backend Config Missing';
            return;
        }
        try {
            const res = await fetch(`${_API_URL}/health`);
            if (res.ok) {
                statusTextEl.textContent = 'Backend Ready';
                pulseDotEl.className     = 'pulse-dot active';
                if (!isGenerating && uploadedFile) generateBtn.disabled = false;
            } else throw new Error();
        } catch {
            statusTextEl.textContent = 'Backend Offline';
            pulseDotEl.className     = 'pulse-dot error';
            if (!isGenerating) generateBtn.disabled = true;
        }
    }

    generateBtn.disabled = true;
    checkBackendStatus();
    initData();
    setInterval(checkBackendStatus, 10000);
});
