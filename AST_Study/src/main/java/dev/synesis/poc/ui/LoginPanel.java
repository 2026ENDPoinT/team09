package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.plaf.basic.BasicButtonUI;
import javax.swing.plaf.LayerUI;
import java.awt.*;
import java.awt.event.HierarchyEvent;
import java.awt.event.MouseEvent;
import java.awt.font.TextAttribute;
import java.awt.geom.Arc2D;
import java.awt.geom.Ellipse2D;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.util.Map;

/** The centered Figma login card with the existing pointer-responsive dot field. */
public final class LoginPanel extends JPanel {
    static final double WAVE_SPACING=576, WAVE_SPEED=228.48;
    private static final int WAVE_FRAME_MILLIS=56,POINTER_FRAME_MILLIS=16;
    private static final double WAVE_FRAME_SECONDS=1.0/18;

    /** Stationary dots sample a periodic crest travelling along (+x,-y). */
    static double diagonalWave(double x,double y,double travel) {
        double phase=((x-y)/Math.sqrt(2)-travel)*Math.PI*2/WAVE_SPACING;
        double crest=(1+Math.cos(phase))*.5;
        return crest*crest;
    }
    private static final String LOGIN_TEXT = "Google로 계속하기";
    private static final Color BACKGROUND = new Color(0xedeff3);
    private static final BufferedImage APP_ICON = loadAppIcon();
    private final GoogleButton login = new GoogleButton();
    private final PaperPanel paper = new PaperPanel();
    private final JLayer<PaperPanel> paperLayer;
    private final Timer animation;
    private long lastFrame;
    private boolean animationPaused;
    private double wavePaintElapsed;

    public LoginPanel(Runnable onLogin) {
        super(null);
        setBackground(BACKGROUND);
        setPreferredSize(new Dimension(1360, 820));
        paperLayer = new JLayer<>(paper, new LayerUI<PaperPanel>() {
            @Override public void installUI(JComponent component) {
                super.installUI(component);
                ((JLayer<?>) component).setLayerEventMask(AWTEvent.MOUSE_MOTION_EVENT_MASK | AWTEvent.MOUSE_EVENT_MASK);
            }
            @Override public void uninstallUI(JComponent component) {
                ((JLayer<?>) component).setLayerEventMask(0);
                super.uninstallUI(component);
            }
            @Override protected void processMouseMotionEvent(MouseEvent event, JLayer<? extends PaperPanel> layer) {
                paper.followPointer(SwingUtilities.convertPoint(event.getComponent(), event.getPoint(), paper));
            }
            @Override protected void processMouseEvent(MouseEvent event, JLayer<? extends PaperPanel> layer) {
                Point point = SwingUtilities.convertPoint(event.getComponent(), event.getPoint(), paper);
                if (event.getID() == MouseEvent.MOUSE_ENTERED) paper.followPointer(point);
                else if (event.getID() == MouseEvent.MOUSE_EXITED && !paper.contains(point)) paper.followPointer(point);
            }
        });
        add(paperLayer);
        login.getAccessibleContext().setAccessibleName(LOGIN_TEXT);
        login.addActionListener(event -> {
            login.setEnabled(false);
            login.setText("로그인 중…");
            LoginTransition.play(login, onLogin);
        });
        paper.add(login);
        animation = new Timer(WAVE_FRAME_MILLIS, event -> tick());
        animation.setCoalesce(true);
        addHierarchyListener(event -> {
            if ((event.getChangeFlags() & HierarchyEvent.SHOWING_CHANGED) == 0) return;
            syncAnimation();
            if(!isShowing())paper.releaseSurface();
        });
        AnimationWindow.observe(this,this::syncAnimation);
    }

    @Override public void doLayout() { paperLayer.setBounds(0, 0, getWidth(), getHeight()); }

    public JButton loginButton() { return login; }

    void setAnimationPaused(boolean paused) {
        animationPaused = paused;
        syncAnimation();
    }

    private void syncAnimation() {
        if(animationPaused||!AnimationWindow.active(this)){animation.stop();return;}
        if(!animation.isRunning()){lastFrame=System.nanoTime();animation.start();}
    }

    public void reset() {
        login.setText(LOGIN_TEXT);
        login.setEnabled(true);
        repaint();
    }

    private void tick() {
        long now = System.nanoTime();
        double delta = Math.min(.10, (now - lastFrame) / 1_000_000_000.0);
        lastFrame = now;
        Rectangle dirty = paper.updateDots(delta);
        wavePaintElapsed+=delta;
        if (dirty != null) {
            boolean waving=paper.waveBlend>0 || paper.pointerOverCard || !paper.pointerInside;
            if(!waving || wavePaintElapsed>=WAVE_FRAME_SECONDS) {
                paper.repaint(dirty);wavePaintElapsed=waving?Math.max(0,wavePaintElapsed-WAVE_FRAME_SECONDS):0;
                paper.lastPaintedPointer.setLocation(paper.pointerX,paper.pointerY);
            }else if(paper.pointerInside&&!paper.pointerOverCard) {
                paper.repaint(paper.pointerRepaintBounds());
            }
        }
        animation.setDelay(paper.pointerInside&&!paper.pointerOverCard?POINTER_FRAME_MILLIS:WAVE_FRAME_MILLIS);
        if (dirty == null) animation.stop();
    }

    private void wakeAnimation() {
        animation.setDelay(paper.pointerInside&&!paper.pointerOverCard?POINTER_FRAME_MILLIS:WAVE_FRAME_MILLIS);
        if (!animationPaused && AnimationWindow.active(this) && !animation.isRunning()) {
            lastFrame = System.nanoTime();
            animation.start();
        }
    }

    private final class PaperPanel extends JPanel {
        private final JLabel logo = new JLabel(new DeviceImageIcon(APP_ICON, 56, 56));
        private final JLabel brand = label("SYNESIS", 21, Font.BOLD, new Color(0x20242a));
        private final JLabel tagline = label("학습에 필요한 모든 도구를 한 곳에서.", 13, Font.PLAIN, new Color(0x8b929c));
        private final JLabel welcome = label("환영합니다.", 20, Font.BOLD, new Color(0x252a31));
        private final JLabel terms = label("<html><div style='text-align:center'>계속하면 SYNESIS의 이용약관 및<br>개인정보처리방침에 동의하게 됩니다.</div></html>",
            10, Font.PLAIN, new Color(0xa0a7b0));
        private final JLabel footer = label("Synesis byC4T(mjKim)", 11, Font.PLAIN, Color.BLACK);
        private Rectangle cardBounds = new Rectangle();
        private double pointerX = -1000, pointerY = -1000;
        private boolean pointerInside;
        private boolean pointerOverCard;
        private double waveTravel,waveBlend;
        private static final double DOT_STEP = 23, DOT_ORIGIN = 15, RESPONSE_RADIUS = 156, PUSH = 11;
        private static final Color[] DOT_COLORS = dotColors();
        private static final Color[] LIGHT_DOT_COLORS = lightDotColors();
        private static final Color[][] BRIGHT_DOT_COLORS=waveColors(DOT_COLORS);
        private static final Color[][] BRIGHT_LIGHT_DOT_COLORS=waveColors(LIGHT_DOT_COLORS);
        private static final float[] BACKDROP_STOPS = {0,.18f,.42f,.50f,.58f,.78f,1};
        private static final Color[] BACKDROP_COLORS = {new Color(0x030303),new Color(0x070707),
            new Color(0x141414),new Color(0x686868),new Color(0xe6e6e6),new Color(0xfcfcfc),Color.WHITE};
        private final Ellipse2D.Double dotShape = new Ellipse2D.Double();
        private double[] dotResponses = new double[0], dotOffsetX = new double[0], dotOffsetY = new double[0];
        private Rectangle activeDotCells;
        private int dotColumns, dotRows;
        private double[] diagonalTargets=new double[0],diagonalResponses=new double[0];
        private LoginDotStamp[] waveStamps=new LoginDotStamp[0];
        private LoginWaveRaster waveRaster;
        private LoginWavePattern wavePattern;
        private LoginDotLayer pointerLayer;
        private boolean patternReady,patternLayoutDirty=true;
        private double stampScaleX,stampScaleY;
        private boolean[] fixedDotDark=new boolean[0];
        private int contrastWidth=-1,contrastHeight,contrastSurfaceWidth,contrastSurfaceHeight;
        private BufferedImage cachedSurface, cachedShadow, cachedCard;
        private int shadowWidth, shadowHeight;
        private int cachedWidth, cachedHeight;
        private double cachedScaleX, cachedScaleY, cardScaleX, cardScaleY;
        private double requestedScaleX=1,requestedScaleY=1;
        private int layoutWidth,layoutHeight;
        private final Timer resizeRefresh=new Timer(140,event->{refreshSurfaceAsync();refreshCardAsync();});
        private SwingWorker<BufferedImage,Void> surfaceWorker;
        private long surfaceEpoch;
        private record CardLayers(BufferedImage shadow,BufferedImage card) {}
        private SwingWorker<CardLayers,Void> cardWorker;
        private long cardEpoch;
        private Point lastPaintedPointer=new Point(-1000,-1000);

        private Rectangle pointerRepaintBounds() {
            int radius=(int)(RESPONSE_RADIUS+PUSH+5);
            Rectangle bounds=new Rectangle((int)pointerX-radius,(int)pointerY-radius,radius*2+1,radius*2+1);
            if(contains(lastPaintedPointer))bounds.add(new Rectangle(lastPaintedPointer.x-radius,lastPaintedPointer.y-radius,radius*2+1,radius*2+1));
            lastPaintedPointer.setLocation(pointerX,pointerY);
            return bounds.intersection(new Rectangle(0,0,getWidth(),getHeight()));
        }

        private Color[] currentDotColors(boolean light) {
            return (light?BRIGHT_LIGHT_DOT_COLORS:BRIGHT_DOT_COLORS)[(int)Math.round(waveBlend*32)];
        }

        private void followPointer(Point point) {
            pointerX=point.x;pointerY=point.y;
            pointerInside=contains(point);
            pointerOverCard=pointerInside && (cardBounds.contains(point) || logo.getBounds().contains(point));
            wakeAnimation();
        }

        private void ensureDots() {
            int columns=Math.max(0,(getWidth()+7)/23),rows=Math.max(0,(getHeight()+7)/23);
            if(columns!=dotColumns || rows!=dotRows) {
                patternReady=false;
                int oldColumns=dotColumns,oldRows=dotRows;
                double[] previousResponses=dotResponses,previousX=dotOffsetX,previousY=dotOffsetY;
                LoginDotStamp[] previousStamps=waveStamps;
                dotColumns=columns;dotRows=rows;
                dotResponses=new double[columns*rows];
                dotOffsetX=new double[columns*rows];dotOffsetY=new double[columns*rows];
                int diagonals=columns+rows;
                diagonalTargets=new double[diagonals];diagonalResponses=new double[diagonals];
                waveStamps=new LoginDotStamp[diagonals*2];
                fixedDotDark=new boolean[columns*rows];contrastWidth=-1;
                // The lattice is anchored at the same origin at every size. Copy
                // existing dots instead of resetting the visible wave on each row/column change.
                for(int row=0;row<rows;row++)for(int col=0;col<columns;col++) {
                    int index=row*columns+col;
                    if(row<oldRows && col<oldColumns) {
                        int previous=row*oldColumns+col;
                        dotResponses[index]=previousResponses[previous];dotOffsetX[index]=previousX[previous];dotOffsetY[index]=previousY[previous];
                    } else if(waveBlend>0) {
                        int oldRow=Math.max(0,row-col),oldCol=Math.max(0,col-row);
                        dotResponses[index]=oldRow<oldRows && oldCol<oldColumns?previousResponses[oldRow*oldColumns+oldCol]
                            :waveBlend*diagonalWave(col*DOT_STEP,row*DOT_STEP,waveTravel);
                    }
                }
                // Reindex small diagonal stamps; keep the large backing buffer alive through a drag.
                for(int diagonal=0;diagonal<diagonals;diagonal++) {
                    int old=diagonal-rows+oldRows;
                    if(old<0 || old*2+1>=previousStamps.length)continue;
                    for(int color=0;color<2;color++){waveStamps[diagonal*2+color]=previousStamps[old*2+color];previousStamps[old*2+color]=null;}
                }
                for(LoginDotStamp stamp:previousStamps)if(stamp!=null)stamp.close();
                activeDotCells=oldColumns>0?new Rectangle(0,0,columns,rows):null;
            }
        }

        private Rectangle updateDots(double delta) {
            ensureDots();
            double ease = 1 - Math.exp(-Math.max(0, delta) / .10);
            boolean waveRequested=pointerOverCard || !pointerInside;
            waveBlend=approach(waveBlend,waveRequested?1:0,ease,.002);
            boolean waving=waveRequested || waveBlend>0;
            if(waving)waveTravel=(waveTravel+Math.max(0,delta)*WAVE_SPEED)%WAVE_SPACING;
            if(waving)for(int diagonal=0;diagonal<diagonalTargets.length;diagonal++)
                diagonalTargets[diagonal]=diagonalWave((diagonal-dotRows)*DOT_STEP,0,waveTravel);
            if(waveRequested&&waveBlend==1&&patternReady) {
                // A resting wave has one response per diagonal. Update it once,
                // then copy rows in bulk for pointer-mode continuity and hit testing.
                for(int d=0;d<diagonalResponses.length;d++)diagonalResponses[d]=approach(diagonalResponses[d],diagonalTargets[d],ease,.002);
                for(int row=0;row<dotRows;row++)System.arraycopy(diagonalResponses,dotRows-row,dotResponses,row*dotColumns,dotColumns);
                return new Rectangle(0,0,getWidth(),getHeight());
            }
            Rectangle cells = activeDotCells;
            if(waving)cells=new Rectangle(0,0,dotColumns,dotRows);
            if (pointerInside) {
                Rectangle nearby = dotCells(new Rectangle((int)pointerX-(int)RESPONSE_RADIUS,(int)pointerY-(int)RESPONSE_RADIUS,(int)RESPONSE_RADIUS*2+1,(int)RESPONSE_RADIUS*2+1), 0);
                cells = cells == null ? nearby : cells.union(nearby);
            }
            if (cells == null || cells.isEmpty()) return null;
            Rectangle dirty = null, nextActive = null;
            int activeLeft=dotColumns,activeTop=dotRows,activeRight=-1,activeBottom=-1;
            for (int row=cells.y; row<cells.y+cells.height; row++) for (int col=cells.x; col<cells.x+cells.width; col++) {
                int index=row*dotColumns+col;
                double x=DOT_ORIGIN+col*DOT_STEP, y=DOT_ORIGIN+row*DOT_STEP;
                double dx=x-pointerX, dy=y-pointerY;
                boolean nearbyPointer=pointerInside && !pointerOverCard && Math.abs(dx)<RESPONSE_RADIUS && Math.abs(dy)<RESPONSE_RADIUS;
                double distance=nearbyPointer?Math.hypot(dx,dy):0;
                double near=nearbyPointer?Math.max(0,1-distance/RESPONSE_RADIUS):0;
                double pointerResponse=near*near*(1-waveBlend);
                double target=pointerResponse+(waving?waveBlend*diagonalTargets[col-row+dotRows]:0);
                // Only the response envelope travels. The marquee never translates dots.
                double targetX=distance>.001?dx/distance*PUSH*pointerResponse:PUSH*pointerResponse;
                double targetY=distance>.001?dy/distance*PUSH*pointerResponse:0;
                double before=dotResponses[index], oldX=dotOffsetX[index], oldY=dotOffsetY[index];
                double after=approach(before,target,ease,.002);
                double nextX=approach(oldX,targetX,ease,.01), nextY=approach(oldY,targetY,ease,.01);
                dotResponses[index]=after;dotOffsetX[index]=nextX;dotOffsetY[index]=nextY;
                if (after!=0 || nextX!=0 || nextY!=0) {
                    activeLeft=Math.min(activeLeft,col);activeTop=Math.min(activeTop,row);
                    activeRight=Math.max(activeRight,col);activeBottom=Math.max(activeBottom,row);
                }
                if (!waving && (after!=before || nextX!=oldX || nextY!=oldY)) {
                    int left=(int)Math.floor(x+Math.min(oldX,nextX))-4, top=(int)Math.floor(y+Math.min(oldY,nextY))-4;
                    Rectangle dot=new Rectangle(left,top,(int)Math.ceil(x+Math.max(oldX,nextX))+5-left,
                        (int)Math.ceil(y+Math.max(oldY,nextY))+5-top);
                    if(dirty==null)dirty=dot;else dirty.add(dot);
                }
            }
            if(activeRight>=0)nextActive=new Rectangle(activeLeft,activeTop,activeRight-activeLeft+1,activeBottom-activeTop+1);
            activeDotCells=nextActive;
            return waving?new Rectangle(0,0,getWidth(),getHeight()):dirty;
        }

        private Rectangle dotCells(Rectangle clip, int margin) {
            int left=Math.max(0,(int)Math.ceil((clip.x-margin-DOT_ORIGIN)/DOT_STEP));
            int top=Math.max(0,(int)Math.ceil((clip.y-margin-DOT_ORIGIN)/DOT_STEP));
            int right=Math.min(dotColumns-1,(int)Math.floor((clip.getMaxX()+margin-DOT_ORIGIN)/DOT_STEP));
            int bottom=Math.min(dotRows-1,(int)Math.floor((clip.getMaxY()+margin-DOT_ORIGIN)/DOT_STEP));
            return new Rectangle(left,top,Math.max(0,right-left+1),Math.max(0,bottom-top+1));
        }

        private void cancelSurfaceWork() {
            surfaceEpoch++;
            if(surfaceWorker!=null)surfaceWorker.cancel(true);
            surfaceWorker=null;
        }

        private void releaseSurface() {
            resizeRefresh.stop();cancelSurfaceWork();
            cancelCardWork();
            cachedSurface=cachedShadow=cachedCard=null;cachedWidth=cachedHeight=0;
            releaseWaveStamps();
            login.releasePaintCache();
            if(pointerLayer!=null){pointerLayer.close();pointerLayer=null;}
        }

        private void cancelCardWork() {
            cardEpoch++;
            if(cardWorker!=null)cardWorker.cancel(true);
            cardWorker=null;
        }

        private void refreshCardAsync() {
            int width=cardBounds.width,height=cardBounds.height;
            double sx=requestedScaleX,sy=requestedScaleY;
            if(width<1 || height<1 || cachedCard!=null && shadowWidth==width && shadowHeight==height
                    && cardScaleX==sx && cardScaleY==sy)return;
            cancelCardWork();long epoch=cardEpoch;
            cardWorker=new SwingWorker<>() {
                @Override protected CardLayers doInBackground() {
                    BufferedImage shadow=cardShadow(width,height);
                    BufferedImage card=new BufferedImage((int)Math.ceil((width+192)*sx),
                        (int)Math.ceil((height+192)*sy),BufferedImage.TYPE_INT_ARGB_PRE);
                    Graphics2D g=card.createGraphics();
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                    try {g.scale(sx,sy);paintCard(g,width,height,shadow);}
                    finally {g.dispose();}
                    return new CardLayers(shadow,card);
                }
                @Override protected void done() {
                    if(isCancelled() || epoch!=cardEpoch)return;
                    cardWorker=null;
                    try {
                        CardLayers layers=get();
                        if(cardBounds.width!=width || cardBounds.height!=height || requestedScaleX!=sx || requestedScaleY!=sy)return;
                        cachedShadow=layers.shadow();cachedCard=layers.card();shadowWidth=width;shadowHeight=height;
                        cardScaleX=sx;cardScaleY=sy;repaint();
                    } catch(java.util.concurrent.CancellationException ignored) {
                    } catch(InterruptedException interrupted) {Thread.currentThread().interrupt();}
                    catch(java.util.concurrent.ExecutionException failure) {
                        java.util.logging.Logger.getLogger(LoginPanel.class.getName()).log(
                            java.util.logging.Level.WARNING,"Cannot refresh login card",failure.getCause());
                    }
                }
            };cardWorker.execute();
        }

        private void releaseWaveStamps() {
            patternReady=false;patternLayoutDirty=true;
            if(wavePattern!=null){wavePattern.close();wavePattern=null;}
            if(waveRaster!=null){waveRaster.release();waveRaster=null;}
            for(int i=0;i<waveStamps.length;i++)if(waveStamps[i]!=null){waveStamps[i].close();waveStamps[i]=null;}
        }

        private boolean prepareWaveStamps(double sx,double sy) {
            // Integer device scales keep the tiny cached raster pixel-aligned.
            // Other scales retain the original vector path. Tiny strips remain
            // reusable across pointer mode instead of allocating another large image on re-entry.
            if(stampScaleX!=sx || stampScaleY!=sy){releaseWaveStamps();stampScaleX=sx;stampScaleY=sy;}
            if(waveBlend<=0 || sx<1 || sy<1 || sx!=Math.rint(sx) || sy!=Math.rint(sy))return false;
            boolean rebuildContrast=contrastWidth!=getWidth() || contrastHeight!=getHeight()
                || contrastSurfaceWidth!=cachedWidth || contrastSurfaceHeight!=cachedHeight;
            if(patternReady&&waveBlend==1&&!rebuildContrast&&(pointerOverCard||!pointerInside))return true;
            java.util.Arrays.fill(diagonalResponses,Double.NaN);
            if(rebuildContrast)patternLayoutDirty=true;
            patternReady=waveBlend==1;
            for(int row=0;row<dotRows;row++)for(int col=0;col<dotColumns;col++) {
                int index=row*dotColumns+col,diagonal=col-row+dotRows;
                double response=dotResponses[index];
                if(Double.isNaN(diagonalResponses[diagonal]) && dotOffsetX[index]==0 && dotOffsetY[index]==0)
                    diagonalResponses[diagonal]=response;
                if(dotOffsetX[index]!=0 || dotOffsetY[index]!=0 || response!=diagonalResponses[diagonal])patternReady=false;
                if(rebuildContrast)fixedDotDark[index]=backdropPosition((DOT_ORIGIN+col*DOT_STEP)*cachedWidth/getWidth(),
                    (DOT_ORIGIN+row*DOT_STEP)*cachedHeight/getHeight(),cachedWidth,cachedHeight)<.51;
            }
            contrastWidth=getWidth();contrastHeight=getHeight();contrastSurfaceWidth=cachedWidth;contrastSurfaceHeight=cachedHeight;
            if(patternReady&&wavePattern==null)wavePattern=new LoginWavePattern(dotColumns,dotRows,fixedDotDark,(int)sx,(int)sy,BRIGHT_DOT_COLORS[32],BRIGHT_LIGHT_DOT_COLORS[32]);
            else if(patternReady&&patternLayoutDirty)wavePattern.configure(dotColumns,dotRows,fixedDotDark);
            if(patternReady)patternLayoutDirty=false;
            return true;
        }

        private void paintWave(Graphics2D g,double sx,double sy,Rectangle clip) {
            int width=(int)Math.ceil(getWidth()*sx),height=(int)Math.ceil(getHeight()*sy);
            if(waveRaster==null || waveRaster.width<width || waveRaster.width>width*2) {
                if(waveRaster!=null)waveRaster.release();
                int capacityWidth=((width+127)/128)*128;
                int capacityHeight=Math.min(128,Math.max(1,(int)(2L*1024*1024/(capacityWidth*4L))));
                waveRaster=new LoginWaveRaster(capacityWidth,capacityHeight);
            }
            int stripHeight=waveRaster.height;
            Graphics2D pixels=(Graphics2D)g.create();
            try {
                pixels.scale(1/sx,1/sy);
                pixels.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
                int first=Math.max(0,(int)Math.floor(clip.y*sy/stripHeight)*stripHeight);
                int end=Math.min(height,(int)Math.ceil(clip.getMaxY()*sy));
                for(int top=first;top<end;top+=stripHeight) {
                    int count=Math.min(stripHeight,height-top);
                    waveRaster.beginRegion(cachedSurface,width,height,top,count);waveRaster.beginDots(g,sx,sy);
                    int firstRow=Math.max(0,(int)Math.ceil((top/sy-DOT_ORIGIN-PUSH-4)/DOT_STEP));
                    int lastRow=Math.min(dotRows-1,(int)Math.floor(((top+count)/sy-DOT_ORIGIN+PUSH+4)/DOT_STEP));
                    for(int row=firstRow;row<=lastRow;row++)for(int col=0;col<dotColumns;col++) {
                        int index=row*dotColumns+col,diagonal=col-row+dotRows;
                        double envelope=dotResponses[index];
                        double radius=1.8*(.7*1.3+(.27*1.8)*envelope)*.9;
                        double x=DOT_ORIGIN+col*DOT_STEP+dotOffsetX[index],y=DOT_ORIGIN+row*DOT_STEP+dotOffsetY[index];
                        if(y+radius+1<top/sy || y-radius-1>(top+count)/sy)continue;
                        boolean fixed=dotOffsetX[index]==0 && dotOffsetY[index]==0;
                        boolean dark=fixed?fixedDotDark[index]:backdropPosition(x*cachedWidth/getWidth(),y*cachedHeight/getHeight(),cachedWidth,cachedHeight)<.51;
                        Color color=currentDotColors(dark)[(int)Math.round(63*envelope*(1-.70*waveBlend))];
                        if(fixed && envelope==diagonalResponses[diagonal]) {
                            int slot=diagonal*2+(dark?1:0);
                            if(waveStamps[slot]==null)waveStamps[slot]=new LoginDotStamp(g,(int)sx,(int)sy);
                            waveStamps[slot].draw(waveRaster,(int)x,(int)y,radius,color);
                        } else waveRaster.vectorDot(x,y,radius,color);
                    }
                    pixels.drawImage(waveRaster.image,0,top,width,top+count,0,0,width,count,null);
                }
            } finally {pixels.dispose();}
        }

        private BufferedImage renderSurface(int width,int height,double sx,double sy) {
            // Ship the usual window sizes as lossless pixels. Other sizes retain
            // the existing asynchronous renderer, so resizing does not distort the boundary.
            if(width==1360 && (height==820 || height==822) && sx==sy && (sx==1 || sx==2)) {
                String name="/login/backdrop-"+width+"x"+height+"@"+(int)sx+"x.png";
                try(var input=LoginPanel.class.getResourceAsStream(name)) {
                    if(input!=null) {
                        BufferedImage baked=ImageIO.read(input);
                        if(baked!=null && baked.getWidth()==width*(int)sx && baked.getHeight()==height*(int)sy) {
                            BufferedImage rgb=new BufferedImage(baked.getWidth(),baked.getHeight(),BufferedImage.TYPE_INT_RGB);
                            Graphics2D copy=rgb.createGraphics();
                            try {copy.setComposite(AlphaComposite.Src);copy.drawImage(baked,0,0,null);}
                            finally {copy.dispose();baked.flush();}
                            return rgb;
                        }
                        if(baked!=null)baked.flush();
                    }
                } catch(IOException ignored) { /* Keep the procedural fallback for missing/corrupt assets. */ }
            }
            BufferedImage image=new BufferedImage(Math.max(1,(int)Math.ceil(width*sx)),
                Math.max(1,(int)Math.ceil(height*sy)),BufferedImage.TYPE_INT_RGB);
            Graphics2D surface=image.createGraphics();
            try {surface.scale(sx,sy);paintBackdrop(surface,width,height);}
            finally {surface.dispose();}
            return LoginBackgroundImage.cache(image,width,height,sx,sy);
        }

        private void refreshSurfaceAsync() {
            int width=getWidth(),height=getHeight();
            double sx=requestedScaleX,sy=requestedScaleY;
            if(width<=0||height<=0)return;
            if(cachedSurface!=null&&cachedWidth==width&&cachedHeight==height&&cachedScaleX==sx&&cachedScaleY==sy)return;
            cancelSurfaceWork();
            long epoch=surfaceEpoch;
            surfaceWorker=new SwingWorker<>() {
                @Override protected BufferedImage doInBackground() {return renderSurface(width,height,sx,sy);}
                @Override protected void done() {
                    if(isCancelled()||epoch!=surfaceEpoch)return;
                    surfaceWorker=null;
                    try {
                        BufferedImage image=get();
                        if(width==getWidth()&&height==getHeight()&&sx==requestedScaleX&&sy==requestedScaleY) {
                            cachedSurface=image;cachedWidth=width;cachedHeight=height;cachedScaleX=sx;cachedScaleY=sy;
                            repaint();
                        } else if(isShowing())resizeRefresh.restart();
                    } catch(java.util.concurrent.CancellationException ignored) {
                        // A more recent size or a hidden login screen superseded this render.
                    } catch(InterruptedException interrupted) {
                        Thread.currentThread().interrupt();
                    } catch(java.util.concurrent.ExecutionException failure) {
                        java.util.logging.Logger.getLogger(LoginPanel.class.getName()).log(
                            java.util.logging.Level.WARNING,"Cannot refresh login backdrop",failure.getCause());
                    }
                }
            };
            surfaceWorker.execute();
        }

        PaperPanel() {
            super(null);
            setBackground(BACKGROUND);
            resizeRefresh.setRepeats(false);
            logo.getAccessibleContext().setAccessibleName("SYNESIS 앱 아이콘");
            brand.setFont(brand.getFont().deriveFont(Map.of(TextAttribute.TRACKING, .28f)));
            for (JLabel label : new JLabel[]{logo, brand, tagline, welcome, terms, footer}) add(label);
        }

        @Override public void doLayout() {
            if(layoutWidth!=getWidth()||layoutHeight!=getHeight()) {
                layoutWidth=getWidth();layoutHeight=getHeight();
                cancelSurfaceWork();
                cancelCardWork();
                if(cachedSurface!=null&&isShowing())resizeRefresh.restart();
            }
            int width = Math.max(1, Math.min(440, getWidth() - 40));
            int height = 374;
            Rectangle next = new Rectangle((getWidth() - width) / 2, (getHeight() - height) / 2, width, height);
            cardBounds=next;
            int x = cardBounds.x, y = cardBounds.y;
            int inset = width < 400 ? 26 : 48;
            int inner = Math.max(1, width - 2 * inset);
            logo.setBounds(x + (width - 56) / 2, y - 28, 56, 56);
            brand.setBounds(x + inset, y + 50, inner, 28);
            tagline.setBounds(x + inset, y + 108, inner, 22);
            fit(tagline, 13, inner);
            welcome.setBounds(x + inset, y + 174, inner, 30);
            login.setBounds(x + inset, y + 232, inner, 54);
            terms.setBounds(x + inset, y + 310, inner, 36);
            footer.setBounds(20, getHeight() - 42, Math.max(1, getWidth() - 40), 18);
        }

        private void paintCachedCard(Graphics2D g) {
            int x=cardBounds.x-96,y=cardBounds.y-96,w=cardBounds.width+192,h=cardBounds.height+192;
            int sourceWidth=shadowWidth+192,sourceHeight=shadowHeight+192;
            if(w==sourceWidth && h==sourceHeight){g.drawImage(cachedCard,x,y,w,h,null);return;}
            // Keep rounded corners, borders and shadow padding fixed while only
            // stretching the middle. A sharp replacement is built after dragging settles.
            int edgeX=Math.min(124,Math.min(w,sourceWidth)/2),edgeY=Math.min(124,Math.min(h,sourceHeight)/2);
            int[] fromX={0,edgeX,sourceWidth-edgeX,sourceWidth},fromY={0,edgeY,sourceHeight-edgeY,sourceHeight};
            int[] toX={x,x+edgeX,x+w-edgeX,x+w},toY={y,y+edgeY,y+h-edgeY,y+h};
            Object interpolation=g.getRenderingHint(RenderingHints.KEY_INTERPOLATION);
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
            for(int row=0;row<3;row++)for(int col=0;col<3;col++)g.drawImage(cachedCard,
                toX[col],toY[row],toX[col+1],toY[row+1],
                (int)Math.round(fromX[col]*cachedCard.getWidth()/(double)sourceWidth),
                (int)Math.round(fromY[row]*cachedCard.getHeight()/(double)sourceHeight),
                (int)Math.round(fromX[col+1]*cachedCard.getWidth()/(double)sourceWidth),
                (int)Math.round(fromY[row+1]*cachedCard.getHeight()/(double)sourceHeight),null);
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,interpolation);
        }

        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g = quality(graphics);
            try {
                int w=getWidth(),h=getHeight();
                if(w<=0 || h<=0)return;
                ensureDots();
                double sx=Math.abs(g.getTransform().getScaleX()),sy=Math.abs(g.getTransform().getScaleY());
                requestedScaleX=sx;requestedScaleY=sy;
                if(cachedSurface==null) {
                    cachedSurface=renderSurface(w,h,sx,sy);
                    cachedWidth=w;cachedHeight=h;cachedScaleX=sx;cachedScaleY=sy;
                }
                boolean surfaceMatches=cachedWidth==w&&cachedHeight==h&&cachedScaleX==sx&&cachedScaleY==sy;
                boolean copyBackground=surfaceMatches&&cachedSurface instanceof LoginBackgroundImage image&&image.canCopyTo(g);
                if(!copyBackground&&cachedSurface instanceof LoginBackgroundImage image)image.restoreRaw();
                if(!surfaceMatches&&isShowing()&&!resizeRefresh.isRunning()&&surfaceWorker==null)resizeRefresh.restart();
                int cw=cardBounds.width,ch=cardBounds.height;
                boolean rebuildCard=cachedCard==null||shadowWidth!=cw||shadowHeight!=ch||cardScaleX!=sx||cardScaleY!=sy;
                boolean rebuildNow=cachedCard==null || shadowWidth==cw && shadowHeight==ch;
                if(cachedShadow==null) {
                    cachedShadow=cardShadow(cw,ch);shadowWidth=cw;shadowHeight=ch;
                }
                if(rebuildCard && rebuildNow) {
                    cachedCard=new BufferedImage((int)Math.ceil((cw+192)*sx),(int)Math.ceil((ch+192)*sy),BufferedImage.TYPE_INT_ARGB_PRE);
                    Graphics2D card=cachedCard.createGraphics();
                    card.setRenderingHints(g.getRenderingHints());
                    try {card.scale(sx,sy);paintCard(card,cw,ch,cachedShadow);}
                    finally {card.dispose();}
                    cardScaleX=sx;cardScaleY=sy;
                }
                if(rebuildCard && !rebuildNow && isShowing() && !resizeRefresh.isRunning() && cardWorker==null)resizeRefresh.restart();
                boolean rasterWave=prepareWaveStamps(sx,sy);
                boolean patternedWave=rasterWave&&patternReady;
                Rectangle clip=g.getClipBounds();
                if(clip==null)clip=new Rectangle(0,0,w,h);
                if(rasterWave&&!patternedWave)paintWave(g,sx,sy,clip);
                else {
                    Graphics2D pixels=(Graphics2D)g.create();
                    try {
                        if(!surfaceMatches)pixels.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
                        if(copyBackground){
                            pixels.scale(1/sx,1/sy);pixels.drawImage(cachedSurface,0,0,null);
                        }else pixels.drawImage(cachedSurface,0,0,w,h,null);
                    } finally {pixels.dispose();}
                }
                if(patternedWave)wavePattern.paint(g,diagonalResponses);
                else if(!rasterWave) {
                    if(LoginDotLayer.supported(g,cachedSurface,w,h,sx,sy)) {
                        if(pointerLayer==null)pointerLayer=new LoginDotLayer();
                        pointerLayer.paint(g,cachedSurface,clip,sx,sy,(tile,area)->paintVectorDots(tile,w,h,area));
                    }else paintVectorDots(g,w,h,clip);
                }
                paintCachedCard(g);
                g.setColor(new Color(0xcbd1d8));
                g.drawLine(w/2-16,h-55,w/2+16,h-55);
            } finally {g.dispose();}
        }

        private void paintVectorDots(Graphics2D g,int w,int h,Rectangle clip) {
            Rectangle cells=dotCells(clip,(int)Math.ceil(PUSH)+4);
            for(int row=cells.y;row<cells.y+cells.height;row++)for(int col=cells.x;col<cells.x+cells.width;col++) {
                int index=row*dotColumns+col;
                double envelope=dotResponses[index];
                double radius=1.8*(.7*1.3+(.27*1.8)*envelope)*.9;
                double x=DOT_ORIGIN+col*DOT_STEP+dotOffsetX[index], y=DOT_ORIGIN+row*DOT_STEP+dotOffsetY[index];
                if(!clip.intersects(x-radius-1,y-radius-1,radius*2+2,radius*2+2))continue;
                boolean dark=backdropPosition(x*cachedWidth/w,y*cachedHeight/h,cachedWidth,cachedHeight)<.51;
                double colorEnvelope=envelope*(1-.70*waveBlend);
                g.setColor(currentDotColors(dark)[(int)Math.round(63*colorEnvelope)]);
                dotShape.setFrame(x-radius,y-radius,radius*2,radius*2);g.fill(dotShape);
            }
        }

        private static void paintBackdrop(Graphics2D g,int w,int h) {
            Graphics2D backdrop=(Graphics2D)g.create();
            backdrop.rotate(Math.toRadians(15),w/2.0,h/2.0);
            backdrop.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_OFF);
            int bleed=(int)Math.ceil(Math.hypot(w,h));
            // A fixed flowing boundary, with a narrow, uneven tonal transition.
            // Resize rebuilds run off the EDT, after dragging has settled.
            try {for(int y=-bleed;y<h+bleed;y++) {
                if((y&31)==0&&Thread.currentThread().isInterrupted())throw new java.util.concurrent.CancellationException();
                double v=y/(double)Math.max(1,h);
                double center=backdropCenter(v)*w,span=backdropSpan(v)*w;
                backdrop.setPaint(new LinearGradientPaint((float)(center-span/2),y,
                    (float)(center+span/2),y,BACKDROP_STOPS,BACKDROP_COLORS));
                backdrop.fillRect(-bleed,y,w+2*bleed,1);
            }} finally {backdrop.dispose();}
        }

        private static double backdropCenter(double y){
            // Continue the upper edge along its tangent instead of curling upward again.
            double join=.24;
            if(y<join){
                double slope=-.84+.065*5.1*Math.cos(join*5.1-.6)
                    +.045*12.7*Math.cos(join*12.7+.8)+.022*23.4*Math.cos(join*23.4-1.1);
                return backdropCenter(join)+slope*(y-join);
            }
            // Drift near the diagonal's ends instead of pinning the corner pixels.
            // Unequal wavelengths keep the bends organic but deterministic.
            return .92-.84*y+.065*Math.sin(y*5.1-.6)
                +.045*Math.sin(y*12.7+.8)+.022*Math.sin(y*23.4-1.1);
        }
        private static double backdropSpan(double y){double wave=Math.sin(y*5.3+.6);return .075+.045*wave*wave;}
        private static double backdropPosition(double x,double y,int w,int h){
            // Inverse of the backdrop rotation, so dot contrast follows the paint.
            double angle=Math.toRadians(15),dx=x-w/2.0,dy=y-h/2.0;
            x=w/2.0+Math.cos(angle)*dx+Math.sin(angle)*dy;
            y=h/2.0-Math.sin(angle)*dx+Math.cos(angle)*dy;
            double v=y/Math.max(1,h),span=backdropSpan(v);
            return (x/Math.max(1,w)-backdropCenter(v))/span+.5;
        }

        private static void paintCard(Graphics2D g,int w,int h,BufferedImage shadow) {
            g.drawImage(shadow,0,0,null);
            g.setColor(new Color(1f,1f,1f,.95f));g.fillRoundRect(96,96,w,h,56,56);
            g.setColor(new Color(148,163,184,61));g.drawRoundRect(96,96,w-1,h-1,56,56);
            g.setColor(new Color(0xcbd1d8));g.drawLine(96+(w-28)/2,191,96+(w+28)/2,191);
            // A small white halo follows the icon tile, baked into the existing card cache.
            // Its lower half naturally disappears against the white card surface.
            double cx=96+w/2.0,cy=96;
            for(int layer=10;layer>=1;layer--) {
                double spread=layer*.7,size=46+spread*2;
                g.setColor(new Color(255,255,255,(int)Math.round((2+(10-layer)/2)*1.35)));
                g.fill(new RoundRectangle2D.Double(cx-size/2,cy-size/2,size,size,12+spread*2,12+spread*2));
            }
        }
    }

    private static double approach(double value,double target,double ease,double tolerance) {
        double next=value+(target-value)*ease;
        return Math.abs(target-next)<tolerance?target:next;
    }

    private static Color[] dotColors() {
        Color[] colors=new Color[64];
        for(int i=0;i<colors.length;i++)colors[i]=new Color(71,85,105,52+i);
        return colors;
    }

    private static Color[] lightDotColors() {
        Color[] colors=new Color[64];
        for(int i=0;i<colors.length;i++) {
            double response=i/63.0;
            int shade=(int)Math.round(81+(255-81)*response);
            int alpha=(int)Math.round(95+(230-95)*response);
            colors[i]=new Color(shade,shade,shade,alpha);
        }
        return colors;
    }

    /** All transition palettes are built once; no per-dot color allocation while animating. */
    private static Color[][] waveColors(Color[] original) {
        Color[][] colors=new Color[33][original.length];
        for(int blend=0;blend<=32;blend++)for(int i=0;i<original.length;i++) {
            Color c=original[i];double brightness=1+.30*blend/32;
            colors[blend][i]=new Color(Math.min(255,(int)Math.round(c.getRed()*brightness)),
                Math.min(255,(int)Math.round(c.getGreen()*brightness)),Math.min(255,(int)Math.round(c.getBlue()*brightness)),c.getAlpha());
        }
        return colors;
    }

    private final class GoogleButton extends JButton {
        private final Icon mark = new GoogleMark();
        private record FrameKey(int width,int height,int pixelsWide,int pixelsHigh,String text,Font font,
                                Color foreground,boolean enabled,boolean pressed,boolean focused) {}
        private FrameKey paintedFrame;
        private BufferedImage restingFrame;
        GoogleButton() {
            super(LOGIN_TEXT);
            setUI(new BasicButtonUI());
            setFont(StudyTheme.font(Font.BOLD, 14));
            setForeground(new Color(0x30363d));
            setOpaque(false);
            setContentAreaFilled(false);
            setBorder(new EmptyBorder(0, 14, 0, 14));
            setFocusPainted(false);
            setRolloverEnabled(false);
            setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        }

        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g=quality(graphics);
            try {
                double sx=Math.abs(g.getTransform().getScaleX()),sy=Math.abs(g.getTransform().getScaleY());
                int pw=Math.max(1,(int)Math.ceil(getWidth()*sx)),ph=Math.max(1,(int)Math.ceil(getHeight()*sy));
                if(sx>0&&sy>0&&(long)pw*ph<=262_144
                        &&g.getTransform().getShearX()==0&&g.getTransform().getShearY()==0) {
                    FrameKey key=new FrameKey(getWidth(),getHeight(),pw,ph,getText(),getFont(),getForeground(),
                        isEnabled(),getModel().isPressed(),isFocusOwner());
                    if(!key.equals(paintedFrame)) {
                        releasePaintCache();restingFrame=new BufferedImage(pw,ph,BufferedImage.TYPE_INT_ARGB_PRE);
                        Graphics2D cache=restingFrame.createGraphics();
                        try {cache.setRenderingHints(g.getRenderingHints());cache.setStroke(g.getStroke());cache.scale(sx,sy);paintButton(cache);}
                        finally{cache.dispose();}
                        paintedFrame=key;
                    }
                    g.drawImage(restingFrame,0,0,getWidth(),getHeight(),null);return;
                }
                paintButton(g);
            } finally {g.dispose();}
        }
        private void releasePaintCache() {
            paintedFrame=null;if(restingFrame!=null){restingFrame.flush();restingFrame=null;}
        }
        private void paintButton(Graphics2D g) {
                int top=2,w=getWidth(),h=getHeight()-5;
                g.setColor(new Color(51,65,85,10));g.fillRoundRect(0,top+3,w-1,h,28,28);
                g.setColor(getModel().isPressed()?new Color(0xf5f6f8):Color.WHITE);
                g.fillRoundRect(0,top,w-1,h,28,28);
                Stroke outlineStroke=g.getStroke();
                paintContent(g,top,w,h);
                g.setStroke(outlineStroke);
                g.setColor(new Color(0xd9dde3));g.drawRoundRect(0,top,w-1,h,28,28);
        }

        private void paintContent(Graphics2D g,int top,int w,int h) {
            if(isFocusOwner()) {
                g.setColor(new Color(71,85,105,46));
                g.setStroke(new BasicStroke(2));g.drawRoundRect(2,top+2,w-5,h-4,26,26);
            }
            mark.paintIcon(this,g,15,top+(h-20)/2);
            g.setFont(getFont());
            g.setColor(isEnabled()?getForeground():new Color(0x8b929c));
            FontMetrics fm=g.getFontMetrics();
            int baseline=top+(h-fm.getHeight())/2+fm.getAscent();
            g.drawString(getText(),(w-fm.stringWidth(getText()))/2,baseline);
            g.setColor(new Color(0x99a1ab));
            int ax=w-22,ay=top+h/2;
            g.setStroke(new BasicStroke(1.2f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            g.drawLine(ax-5,ay,ax+5,ay);g.drawLine(ax+1,ay-4,ax+5,ay);g.drawLine(ax+1,ay+4,ax+5,ay);
        }
    }

    private static final class GoogleMark implements Icon {
        public int getIconWidth() { return 20; }
        public int getIconHeight() { return 20; }
        public void paintIcon(Component component, Graphics graphics, int x, int y) {
            Graphics2D g = quality(graphics);
            try {
                g.translate(x, y);
                g.setStroke(new BasicStroke(3.7f, BasicStroke.CAP_BUTT, BasicStroke.JOIN_ROUND));
                Color[] colors = {new Color(0x4285f4), new Color(0x34a853), new Color(0xfbbc05), new Color(0xea4335)};
                int[] starts = {0, 225, 155, 40}, extents = {-135, -70, -70, 115};
                for (int i = 0; i < 4; i++) {
                    g.setColor(colors[i]);
                    g.draw(new Arc2D.Double(2.5, 2.5, 15, 15, starts[i], extents[i], Arc2D.OPEN));
                }
                g.setColor(colors[0]);
                g.fillRect(10, 8, 9, 4);
            } finally { g.dispose(); }
        }
    }

    private static BufferedImage cardShadow(int width, int height) {
        int padding = 48;
        int w = (width + 1) / 2 + padding * 2, h = (height + 1) / 2 + padding * 2;
        float[] coverage = new float[w * h];
        for (int layer = 0; layer < 2; layer++) {
            BufferedImage mask = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
            Graphics2D g = mask.createGraphics();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(Color.WHITE);
                g.fillRoundRect(padding, padding + (layer == 0 ? 6 : 2),
                    (width + 1) / 2, (height + 1) / 2, 28, 28);
            } finally { g.dispose(); }
            // Blur opaque coverage in floating point. Blurring a faint premultiplied
            // color twice quantizes its tails into the rectangular bands seen on screen.
            float[] blurred = blurCoverage(mask, layer == 0 ? 12 : 4);
            float opacity = layer == 0 ? .08f : .035f;
            for (int i = 0; i < coverage.length; i++)
                coverage[i] = 1 - (1 - coverage[i]) * (1 - blurred[i] * opacity);
        }
        BufferedImage result = new BufferedImage(w * 2, h * 2, BufferedImage.TYPE_INT_ARGB);
        int[] pixels = new int[result.getWidth() * result.getHeight()];
        // Quantize only once at the final size; sub-alpha coverage fades out without a hard contour.
        int[] threshold = {0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5};
        for (int y = 0; y < result.getHeight(); y++) {
            checkRenderCancelled(y);
            for (int x = 0; x < result.getWidth(); x++) {
            double px = Math.max(0, Math.min(w - 1, (x + .5) / 2 - .5));
            double py = Math.max(0, Math.min(h - 1, (y + .5) / 2 - .5));
            int left = (int) px, top = (int) py, right = Math.min(w - 1, left + 1), bottom = Math.min(h - 1, top + 1);
            double fx = px - left, fy = py - top;
            double upper = coverage[top * w + left] * (1 - fx) + coverage[top * w + right] * fx;
            double lower = coverage[bottom * w + left] * (1 - fx) + coverage[bottom * w + right] * fx;
            double alpha = Math.max(0, (upper * (1 - fy) + lower * fy) * 255);
            int quantized = Math.min(255, (int) Math.floor(alpha + (threshold[(y & 3) * 4 + (x & 3)] + .5) / 16));
            pixels[y * result.getWidth() + x] = quantized << 24 | 0x334155;
        }
        }
        result.setRGB(0, 0, result.getWidth(), result.getHeight(), pixels, 0, result.getWidth());
        return result;
    }

    private static float[] blurCoverage(BufferedImage mask, float sigma) {
        int w = mask.getWidth(), h = mask.getHeight(), radius = (int) (sigma * 3);
        float[] kernel = new float[radius * 2 + 1];
        double sum = 0;
        for (int i = 0; i < kernel.length; i++) {
            double distance = i - radius;
            kernel[i] = (float) Math.exp(-distance * distance / (2 * sigma * sigma));
            sum += kernel[i];
        }
        for (int i = 0; i < kernel.length; i++) kernel[i] /= (float) sum;
        int[] pixels = mask.getRGB(0, 0, w, h, null, 0, w);
        float[] horizontal = new float[w * h], blurred = new float[w * h];
        for (int y = 0; y < h; y++) {
            checkRenderCancelled(y);
            for (int x = 0; x < w; x++) {
            double alpha = 0;
            for (int k = Math.max(-radius, -x); k <= Math.min(radius, w - 1 - x); k++)
                alpha += (pixels[y * w + x + k] >>> 24) / 255.0 * kernel[k + radius];
            horizontal[y * w + x] = (float) alpha;
        }
        }
        for (int y = 0; y < h; y++) {
            checkRenderCancelled(y);
            for (int x = 0; x < w; x++) {
            double alpha = 0;
            for (int k = Math.max(-radius, -y); k <= Math.min(radius, h - 1 - y); k++)
                alpha += horizontal[(y + k) * w + x] * kernel[k + radius];
            blurred[y * w + x] = (float) alpha;
        }
        }
        return blurred;
    }

    private static void checkRenderCancelled(int row) {
        if((row&31)==0 && Thread.currentThread().isInterrupted())throw new java.util.concurrent.CancellationException();
    }

    private static BufferedImage loadAppIcon() {
        try (var stream = LoginPanel.class.getResourceAsStream("/dev/synesis/poc/synesis-logo.png")) {
            if (stream == null) throw new IllegalStateException("Missing SYNESIS app icon");
            BufferedImage image = ImageIO.read(stream);
            if (image == null) throw new IllegalStateException("Invalid SYNESIS app icon");
            return image;
        } catch (IOException error) { throw new IllegalStateException("Cannot read SYNESIS app icon", error); }
    }

    private static JLabel label(String text, int size, int style, Color color) {
        JLabel label = new JLabel(text, SwingConstants.CENTER);
        label.setFont(StudyTheme.font(style, size));
        label.setForeground(color);
        return label;
    }

    private static void fit(JLabel label, int size, int width) {
        Font font = StudyTheme.font(Font.PLAIN, size);
        while (size > 9 && label.getFontMetrics(font).stringWidth(label.getText()) > width)
            font = StudyTheme.font(Font.PLAIN, --size);
        label.setFont(font);
    }

    private static Graphics2D quality(Graphics graphics) {
        Graphics2D g = (Graphics2D) graphics.create();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
        return g;
    }

}
