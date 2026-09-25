// Generate a minimal valid .ico (256x256 BMP frame) with the BotConnector diamond mark.
const fs=require('node:fs');
const W=256,H=256;
// BMP (BITMAPINFOHEADER) pixel data: rows bottom-up, BGRA, plus AND mask.
const px=Buffer.alloc(W*H*4);
const mask=Buffer.alloc(Math.ceil(W/8)*H); // all zeros = opaque
function setPx(x,y,r,g,b){const row=H-1-y;const off=(row*W+x)*4;px[off]=b;px[off+1]=g;px[off+2]=r;px[off+3]=255;}
for(let y=0;y<H;y++)for(let x=0;x<W;x++){
  // dark background
  let r=10,g=13,b=16;
  // diamond mark (green #8df0c4) centered, scaled to 256x256
  const cx=127.5,cy=127.5;
  const dx=Math.abs(x-cx),dy=Math.abs(y-cy);
  const size=72; // half-diagonal of diamond
  if(dx+dy<=size){r=141;g=240;b=196;}
  if(dx+dy<=size&&Math.abs(dx-dy)<=2){r=10;g=13;b=16;} // cross line
  setPx(x,y,r,g,b);
}
const bih=Buffer.alloc(40);
bih.writeUInt32LE(40,0);bih.writeInt32LE(W,4);bih.writeInt32LE(H*2,8);bih.writeUInt16LE(1,12);bih.writeUInt16LE(32,14);
const image=Buffer.concat([bih,px,mask]);
// ICO header
const header=Buffer.alloc(6);header.writeUInt16LE(0,0);header.writeUInt16LE(1,2);header.writeUInt16LE(1,4);
const entry=Buffer.alloc(16);
entry[0]=W;entry[1]=H;entry[2]=0;entry[3]=0;
entry.writeUInt16LE(1,4);entry.writeUInt16LE(32,6);
entry.writeUInt32LE(image.length,8);entry.writeUInt32LE(22,12);
fs.writeFileSync('assets/botconnector.ico',Buffer.concat([header,entry,image]));
console.log('ico written:',fs.statSync('assets/botconnector.ico').size,'bytes');
