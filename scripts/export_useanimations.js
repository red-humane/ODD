const fs = require('fs');
const path = require('path');
const vm = require('vm');

const tempDir = path.join(__dirname, '..', 'temp_anim', 'package');
const indexSrc = fs.readFileSync(path.join(tempDir, 'index.js'), 'utf8');

const startMarker = '//#region src/player/matrix.ts';
const endMarker = '//#region src/styles.ts';
const playerCode = indexSrc.slice(indexSrc.indexOf(startMarker), indexSrc.indexOf(endMarker));

function createMockElement(tag, attrs = {}) {
    const el = {
        tag,
        attrs: { ...attrs },
        children: [],
        style: {},
        setAttribute(k, v) { this.attrs[k] = String(v); },
        getAttribute(k) { return this.attrs[k]; },
        removeAttribute(k) { delete this.attrs[k]; },
        appendChild(child) { this.children.push(child); return child; },
        append(...children) { for (const c of children) this.children.push(c); },
        remove() {},
        toXml() {
            let str = '<' + this.tag;
            for (const [k, v] of Object.entries(this.attrs)) {
                str += ' ' + k + '="' + String(v).replace(/"/g, '&quot;') + '"';
            }
            if (this.style && Object.keys(this.style).length > 0) {
                let s = Object.entries(this.style).map(([k, v]) => k + ':' + v).join(';');
                str += ' style="' + s + '"';
            }
            if (this.children.length === 0) return str + '/>';
            str += '>';
            for (const c of this.children) str += c.toXml ? c.toXml() : String(c);
            str += '</' + this.tag + '>';
            return str;
        }
    };
    return el;
}

const sandbox = {
    document: {
        createElementNS: (ns, tag) => createMockElement(tag)
    },
    Math, Array, String, Number, Boolean, Object, Map, WeakMap, Set, console
};

const context = vm.createContext(sandbox);
vm.runInContext(playerCode, context);

const iconList = [
    'smartphone',
    'wifi',
    'wifiOff',
    'bluetooth',
    'download',
    'fileText',
    'folderPlus',
    'copy',
    'volume',
    'camera',
    'battery',
    'batteryCharging',
    'scissors',
    'clock'
];

const bundle = {};

for (const name of iconList) {
    const iconModule = require(path.join(tempDir, 'lib', `${name}.js`)).default;
    const animData = iconModule.animationData;
    const totalFrames = animData.op - animData.ip;
    const fr = animData.fr || 30;
    const interaction = iconModule.interaction || 'hover-replay';

    const player = new context.Player({
        container: createMockElement('div'),
        animationData: animData
    });

    const frames = [];
    // If an animation has 120 frames (like download), we can sample every 2 frames for 60 frames or keep all
    const step = (totalFrames > 60) ? 2 : 1;

    for (let f = 0; f < totalFrames; f += step) {
        player.goToAndStop(f);
        let xml = player.renderer.svg.toXml();
        // Replace rgb(0,0,0) and #000000 with {color} for dynamic theme tinting
        xml = xml.replace(/stroke="rgb\(0,\s*0,\s*0\)"/g, 'stroke="{color}"');
        xml = xml.replace(/fill="rgb\(0,\s*0,\s*0\)"/g, 'fill="{color}"');
        xml = xml.replace(/stroke="#000000"/g, 'stroke="{color}"');
        xml = xml.replace(/fill="#000000"/g, 'fill="{color}"');
        frames.push(xml);
    }

    bundle[name] = {
        name,
        width: animData.w || 32,
        height: animData.h || 32,
        fps: fr,
        interaction,
        total_frames: frames.length,
        frames
    };

    console.log(`Exported ${name}: ${frames.length} frames, fps=${fr}, interaction=${interaction}`);
}

const outDir = path.join(__dirname, '..', 'assets', 'animations');
if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
}

const outPath = path.join(outDir, 'useanimations.json');
fs.writeFileSync(outPath, JSON.stringify(bundle), 'utf8');
console.log(`Saved bundle to ${outPath} (${(fs.statSync(outPath).size / 1024).toFixed(1)} KB)`);
