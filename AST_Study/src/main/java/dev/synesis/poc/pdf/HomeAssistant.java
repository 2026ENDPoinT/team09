package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.AppPaths;
import dev.synesis.poc.ui.AccessibleInputs;
import dev.synesis.poc.ui.AssistantAvatar;
import dev.synesis.poc.ui.HoverMotion;
import dev.synesis.poc.ui.LibraryDesign;
import dev.synesis.poc.ui.RoundedPopupMenuUI;
import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.geom.*;
import java.nio.file.*;
import java.time.*;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** A window-owned home overlay with an assistant-only local capability dispatcher. */
public final class HomeAssistant extends JPanel implements AutoCloseable {
    private static final Color INK=new Color(0x203654), ACCENT=new Color(0x5479BA);
    private static final Color BUTTON_BACKGROUND=new Color(0x323a48);
    private static final Font CHAT_FONT=dev.synesis.poc.ui.MistWorkspaceTheme.font(Font.PLAIN,14);
    private static final int PREPARING_BUBBLE_DELAY_MS=450;
    private final Orb orb=new Orb();
    private final ChatCard card=new ChatCard();
    private final AssistantConnectivity connectivity=new AssistantConnectivity();
    private final JComponent resizeGrip=new JComponent(){
        @Override protected void paintComponent(Graphics graphics){
            graphics.setColor(AssistantChatTheme.MUTED);
            graphics.drawLine(4,11,11,4);graphics.drawLine(4,7,7,4);
        }
    };
    private final JComponent resizeGripSE=new JComponent(){
        @Override protected void paintComponent(Graphics graphics){
            graphics.setColor(AssistantChatTheme.MUTED);
            graphics.drawLine(3,10,10,3);graphics.drawLine(7,10,10,7);
        }
    };
    private Point orbCenter,cardAnchor;
    private Point cardMoveTarget;
    private double cardMoveX,cardMoveY;
    private static final int MAX_CARD_WIDTH=750,MAX_CARD_HEIGHT=940;
    private int requestedCardWidth=460,requestedCardHeight=640;
    private boolean resizing,resizePending;
    private Point resizeOrbStart,resizeCornerStart;
    private ChatBubble enteringUser,enteringAnswer;
    private long entranceStarted;
    private boolean paintingEntrance;
    private Rectangle entranceDamage;
    private java.awt.image.BufferedImage entranceSnapshot;
    private int entranceScrollMode;
    private double entranceProgress(){return Math.min(1,Math.max(0,(System.nanoTime()-entranceStarted)/600_000_000d));}
    private static double entranceEase(double value){double t=Math.max(0,Math.min(1,value));return t*t*(3-2*t);}
    private static double sendSpring(double value){
        double t=Math.max(0,Math.min(1,value));
        // A single restrained overshoot, with an exact resting scale at the end.
        double end=1-Math.exp(-7)*(Math.cos(10)+.7*Math.sin(10));
        return (1-Math.exp(-7*t)*(Math.cos(10*t)+.7*Math.sin(10*t)))/end;
    }
    private void startSendEntrance(ChatBubble user,ChatBubble answer){
        answer.awaitingServer=true;answer.setVisible(false);if(answer.gapAfter!=null)answer.gapAfter.setVisible(false);messages.revalidate();
        if(!expanded||Boolean.getBoolean("synesis.reduceMotion"))return;
        enteringUser=user;enteringAnswer=answer;entranceStarted=System.nanoTime();
        entranceScrollMode=scroll.getViewport().getScrollMode();
        scroll.getViewport().setScrollMode(JViewport.SIMPLE_SCROLL_MODE);
        motion.setDelay(16);
    }
    private void finishSendEntrance(){
        if(enteringUser!=null&&(answerBubble==null||answerBubble.arrivalStarted==0))scroll.getViewport().setScrollMode(entranceScrollMode);
        if(entranceSnapshot!=null){entranceSnapshot.flush();entranceSnapshot=null;}
        enteringUser=null;enteringAnswer=null;entranceDamage=null;
        motion.setDelay(answerBubble!=null&&answerBubble.arrivalStarted>0?16:33);card.repaint();
    }
    private void paintSendEntrance(Graphics graphics){
        if(enteringUser==null||enteringUser.getWidth()<=0)return;
        if(entranceSnapshot==null){
            int width=enteringUser.getWidth(),height=enteringUser.getHeight();
            // One short-lived, 1x message image only; never retain a chat/window cache.
            if(height<=0)return;
            if((long)width*height>262144){finishSendEntrance();return;}
            entranceSnapshot=new java.awt.image.BufferedImage(width,height,java.awt.image.BufferedImage.TYPE_INT_ARGB_PRE);
            Graphics2D cache=entranceSnapshot.createGraphics();
            try{paintingEntrance=true;enteringUser.printAll(cache);}
            finally{paintingEntrance=false;cache.dispose();}
        }
        double progress=entranceProgress(),grow=sendSpring(progress/.78);
        double flight=Math.max(0,Math.min(1,(progress-.08)/.86));
        double rise=1-Math.pow(1-flight,3);
        Point destination=SwingUtilities.convertPoint(enteringUser,0,0,card);
        Point origin=SwingUtilities.convertPoint(composer,0,0,card);
        double scale=.16+.84*grow;
        double x=destination.x+(enteringUser.getWidth()*(1-scale));
        double startY=origin.y+Math.min(18,composer.getHeight()/4);
        double y=startY+(destination.y-startY)*rise-14*Math.sin(Math.PI*rise);
        Rectangle damage=new Rectangle((int)x-2,(int)y-2,(int)Math.ceil(enteringUser.getWidth()*scale)+4,(int)Math.ceil(enteringUser.getHeight()*scale)+4);
        entranceDamage=damage;
        Graphics2D g=(Graphics2D)graphics.create();
        try{
            g.clipRect(0,0,card.getWidth(),card.getHeight());
            g.translate(x,y);g.scale(scale,scale);
            g.setComposite(AlphaComposite.SrcOver.derive((float)entranceEase(progress/.18)));
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            g.drawImage(entranceSnapshot,0,0,null);
        }finally{g.dispose();}
    }
    private final JPanel messages=new MessageColumn();
    private final JScrollPane scroll=new dev.synesis.poc.ui.UnifiedScrollPane(messages);
    private final AccessibleInputs.TextArea input=new AccessibleInputs.TextArea(){
        @Override protected void paintComponent(Graphics graphics){super.paintComponent(graphics);if(getText().isEmpty()&&!isFocusOwner()){graphics.setColor(new Color(0x8C96A4));graphics.setFont(getFont());graphics.drawString("어떤 도움이 필요한가요?",getInsets().left,getInsets().top+getFontMetrics(getFont()).getAscent());}}
    };
    private dev.synesis.poc.ui.GrowingTutorInput composer;
    private final JButton send=new AssistantButton("보내기"),fresh=new AssistantButton("새 대화"),history=new AssistantButton("대화내역"),settings=new AssistantButton("설정"),attach=new AssistantButton("＋");
    private final JLabel status=new JLabel("개인 학습 에이전트 · 필요한 자료는 웹에서 확인해요");
    private final ExecutorService worker=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"home-assistant");t.setDaemon(true);return t;});
    private final javax.swing.Timer motion=new javax.swing.Timer(33,e->animate());
    private final javax.swing.Timer revealTimer=new javax.swing.Timer(40,e->reveal());
    private final TutorTextReveal reveal=new TutorTextReveal(2,40);
    private final AtomicReference<String> pending=new AtomicReference<>();
    private final Path folder=AppPaths.account().resolve("assistant");
    private final AssistantConversations conversations=new AssistantConversations(folder);
    private boolean restoringHistory,loadingConversation;
    private int visibleHistoryTurns=30;
    private final AssistantLocal local=new AssistantLocal();
    private final AssistantAttachments attachments=new AssistantAttachments(folder,text->status.setText(text),this::attachmentChanged);
    private JsonObject memory=new JsonObject();
    private JsonObject receipts=new JsonObject();
    private JsonObject imageHistory=new JsonObject();
    private JsonObject deliveryHistory=new JsonObject();
    private String session=UUID.randomUUID().toString(),completedAnswer,completionStatus;
    private ChatBubble answerBubble;
    private volatile PdfProcess process;
    private boolean busy,loaded,ready,closed,expanded,hover;
    private boolean bottomScrollPending;
    private float hoverAmount,opening=1,contentOpening=1;
    private int cardBaseY;
    private long lastTick=System.nanoTime();
    private final WindowAdapter activity=new WindowAdapter(){
        @Override public void windowActivated(WindowEvent e){refreshAnimation();}
        @Override public void windowDeactivated(WindowEvent e){motion.stop();revealTimer.stop();connectivity.monitor(false);completeHiddenAnswer();}
    };
    private Window attachedWindow;
    private final Runnable dataChanged;

    public void setLibraryUi(AssistantLibraryUi bridge){local.attachLibrary(bridge);}
    public HomeAssistant(){this(()->{});}
    public HomeAssistant(Runnable dataChanged){
        this.dataChanged=dataChanged;
        setLayout(null);setOpaque(false);messages.setLayout(new BoxLayout(messages,BoxLayout.Y_AXIS));
        // Swing otherwise skips listener-free lightweight surfaces when selecting
        // a mouse target, allowing blank chat areas to reach the library underneath.
        MouseAdapter shield=new MouseAdapter(){
            @Override public void mousePressed(MouseEvent e){e.consume();}
            @Override public void mouseReleased(MouseEvent e){e.consume();}
            @Override public void mouseClicked(MouseEvent e){e.consume();}
            @Override public void mouseDragged(MouseEvent e){e.consume();}
            @Override public void mouseMoved(MouseEvent e){e.consume();}
            @Override public void mouseWheelMoved(MouseWheelEvent e){e.consume();}
        };
        addMouseListener(shield);addMouseMotionListener(shield);addMouseWheelListener(shield);
        card.addMouseListener(shield);card.addMouseMotionListener(shield);card.addMouseWheelListener(shield);
        messages.setBackground(AssistantChatTheme.BACKGROUND);scroll.setBorder(null);scroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        scroll.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
        scroll.getViewport().setBackground(AssistantChatTheme.BACKGROUND);
        scroll.setBackground(AssistantChatTheme.BACKGROUND);
        scroll.getVerticalScrollBar().setUI(new dev.synesis.poc.ui.FadingScrollBarUI(AssistantChatTheme.MUTED,.38f));
        JPanel header=new JPanel(new BorderLayout(8,0));header.setOpaque(false);
        JLabel title=new JLabel("Personal 에이전트",new SparkIcon(20,AssistantChatTheme.TEXT),SwingConstants.LEFT);title.setFont(LibraryDesign.medium(17));title.setForeground(AssistantChatTheme.TEXT);
        JButton close=new AssistantButton("×");close.setToolTipText("채팅창 접기");close.addActionListener(e->toggle());
        styleButton(close,false);close.setPreferredSize(new Dimension(30,30));
        JPanel headerActions=new JPanel(new BorderLayout(10,0));headerActions.setOpaque(false);headerActions.add(connectivity);headerActions.add(close,BorderLayout.EAST);
        header.add(title);header.add(headerActions,BorderLayout.EAST);
        JPanel toolbar=new JPanel(new BorderLayout(8,0));toolbar.setOpaque(false);
        JLabel subtitle=new JLabel("나의 공부와 일상을 함께 정리해요");subtitle.setForeground(AssistantChatTheme.MUTED);subtitle.setFont(LibraryDesign.medium(11));
        styleButton(fresh,false);fresh.setText("＋ 새 채팅");styleButton(history,false);history.setToolTipText("이전 대화 선택");
        styleButton(settings,false);settings.setToolTipText("저장된 사용자 맞춤 지침 보기");
        JPanel conversationActions=new JPanel(new FlowLayout(FlowLayout.RIGHT,6,0));conversationActions.setOpaque(false);conversationActions.add(settings);conversationActions.add(history);conversationActions.add(fresh);
        toolbar.add(subtitle);toolbar.add(conversationActions,BorderLayout.EAST);
        JPanel north=new JPanel(new BorderLayout(0,10));north.setOpaque(false);north.add(header,BorderLayout.NORTH);north.add(toolbar);
        north.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createMatteBorder(0,0,1,0,AssistantChatTheme.LINE),BorderFactory.createEmptyBorder(0,0,12,0)));
        card.setLayout(new BorderLayout(0,8));card.setBorder(BorderFactory.createEmptyBorder(15,16,14,16));
        card.add(north,BorderLayout.NORTH);card.add(scroll);
        input.setLineWrap(true);input.setWrapStyleWord(true);input.setRows(1);input.setFont(LibraryDesign.medium(14));
        input.setBorder(BorderFactory.createEmptyBorder(3,3,3,3));input.setOpaque(false);
        input.setForeground(AssistantChatTheme.TEXT);input.setCaretColor(AssistantChatTheme.TEXT);
        input.setSelectionColor(new Color(0x4b6083));input.setSelectedTextColor(Color.WHITE);
        input.getAccessibleContext().setAccessibleName("개인 학습 에이전트에게 메시지 입력");
        JScrollPane inputScroll=new dev.synesis.poc.ui.UnifiedScrollPane(input);inputScroll.setBorder(null);inputScroll.setOpaque(false);inputScroll.getViewport().setOpaque(false);
        inputScroll.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
        JPanel actions=new JPanel(new BorderLayout(8,0));actions.setOpaque(false);
        JLabel hint=new JLabel("Enter 전송 · Shift+Enter 줄바꿈");hint.setFont(LibraryDesign.medium(10));hint.setForeground(AssistantChatTheme.MUTED);
        send.setText("");send.setIcon(new Icon(){public int getIconWidth(){return 16;}public int getIconHeight(){return 16;}public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(Color.WHITE);g.setStroke(new BasicStroke(1.8f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));g.drawLine(x+8,y+14,x+8,y+2);g.drawLine(x+8,y+2,x+3,y+7);g.drawLine(x+8,y+2,x+13,y+7);g.dispose();}});styleButton(send,true);send.setFont(LibraryDesign.medium(22));send.setPreferredSize(new Dimension(34,32));send.setToolTipText("메시지 보내기");
        styleButton(attach,false);attach.setToolTipText("이미지 첨부 · 붙여넣기도 가능해요 (최대 8장)");attach.setPreferredSize(new Dimension(30,30));attach.addActionListener(e->attachments.choose(this));
        actions.add(attach,BorderLayout.WEST);actions.add(hint);actions.add(send,BorderLayout.EAST);
        composer=new dev.synesis.poc.ui.GrowingTutorInput(input,inputScroll,attachments.panel,actions,AssistantChatTheme.SURFACE,AssistantChatTheme.LINE);
        attachments.installPaste(input);
        dev.synesis.poc.ui.GrowingTutorInput.focusOnBlankSpace(composer,input);
        JPanel south=new JPanel(new BorderLayout(0,5));south.setOpaque(false);south.add(composer);
        status.setFont(LibraryDesign.medium(10));status.setForeground(AssistantChatTheme.MUTED);south.add(status,BorderLayout.SOUTH);
        card.add(south,BorderLayout.SOUTH);add(card);add(orb);card.setVisible(false);
        add(resizeGrip);setComponentZOrder(resizeGrip,0);resizeGrip.setVisible(false);
        resizeGrip.setCursor(Cursor.getPredefinedCursor(Cursor.NW_RESIZE_CURSOR));
        resizeGrip.setToolTipText("드래그해서 채팅창 크기 조절");
        installResizeGrip(resizeGrip,false);
        add(resizeGripSE);setComponentZOrder(resizeGripSE,0);resizeGripSE.setVisible(false);
        resizeGripSE.setCursor(Cursor.getPredefinedCursor(Cursor.SE_RESIZE_CURSOR));
        resizeGripSE.setToolTipText("드래그해서 채팅창 크기 조절");
        installResizeGrip(resizeGripSE,true);
        setComponentZOrder(orb,0);
        send.addActionListener(e->{if(busy)cancelReply();else send();});fresh.addActionListener(e->resetConversation());history.addActionListener(e->showConversations());settings.addActionListener(e->showPreferences());
        input.getInputMap().put(KeyStroke.getKeyStroke("ENTER"),"assistant-send");
        input.getActionMap().put("assistant-send",new AbstractAction(){public void actionPerformed(ActionEvent e){
            send();
        }});
        input.getInputMap().put(KeyStroke.getKeyStroke("shift ENTER"),"insert-break");
        getInputMap(WHEN_ANCESTOR_OF_FOCUSED_COMPONENT).put(KeyStroke.getKeyStroke("ESCAPE"),"fold");
        getActionMap().put("fold",new AbstractAction(){public void actionPerformed(ActionEvent e){if(expanded)toggle();}});
        addHierarchyListener(e->{if((e.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0)refreshAnimation();});
        welcome();
    }
    private void installResizeGrip(JComponent grip,boolean southeast){
        MouseAdapter resize=new MouseAdapter(){
            private Point pressed;private Rectangle initial;
            @Override public void mousePressed(MouseEvent e){
                if(!SwingUtilities.isLeftMouseButton(e))return;
                pressed=SwingUtilities.convertPoint(grip,e.getPoint(),HomeAssistant.this);initial=card.getBounds();
                if(southeast){
                    resizeOrbStart=new Point(orb.getX()+178+ORB_HINT_PADDING,orb.getY()+40);
                    resizeCornerStart=new Point(initial.x+initial.width,initial.y+initial.height);
                }
                resizing=true;cardMoveTarget=null;finishSendEntrance();motion.setDelay(16);card.releaseSnapshot();
                if(answerBubble!=null){answerBubble.arrivalStarted=0;answerBubble.releaseArrival();}e.consume();
            }
            @Override public void mouseDragged(MouseEvent e){
                if(pressed==null)return;
                Point current=SwingUtilities.convertPoint(grip,e.getPoint(),HomeAssistant.this);
                int dx=current.x-pressed.x,dy=current.y-pressed.y;
                requestedCardWidth=Math.max(460,Math.min(Math.min(MAX_CARD_WIDTH,Math.max(460,getWidth()-32)),initial.width+(southeast?dx:-dx)));
                requestedCardHeight=Math.max(640,Math.min(Math.min(MAX_CARD_HEIGHT,Math.max(640,getHeight()-112)),initial.height+(southeast?dy:-dy)));
                cardAnchor=southeast?initial.getLocation():new Point(initial.x+initial.width-requestedCardWidth,initial.y+initial.height-requestedCardHeight);
                resizePending=true;e.consume();
            }
            @Override public void mouseReleased(MouseEvent e){
                applyPendingResize();resizing=false;motion.setDelay(33);
                resizeOrbStart=null;resizeCornerStart=null;pressed=null;initial=null;e.consume();
            }
        };
        grip.addMouseListener(resize);grip.addMouseMotionListener(resize);
    }
    @Override public void addNotify(){super.addNotify();attachedWindow=SwingUtilities.getWindowAncestor(this);if(attachedWindow!=null)attachedWindow.addWindowListener(activity);refreshAnimation();}
    @Override public void removeNotify(){connectivity.monitor(false);motion.stop();if(attachedWindow!=null)attachedWindow.removeWindowListener(activity);attachedWindow=null;card.releaseSnapshot();super.removeNotify();}
    public void setHomeVisible(boolean visible){
        if(!visible){if(answerBubble!=null){answerBubble.arrivalStarted=0;answerBubble.releaseArrival();}finishSendEntrance();card.releaseSnapshot();opening=expanded?1:0;contentOpening=expanded?1:0;card.setVisible(expanded);}
        setVisible(visible);refreshAnimation();
    }
    private void refreshAnimation(){
        boolean active=!closed&&isShowing()&&(attachedWindow==null||attachedWindow.isActive());
        if(active){lastTick=System.nanoTime();motion.start();if(busy&&expanded)revealTimer.start();else revealTimer.stop();}else {motion.stop();revealTimer.stop();}
        connectivity.monitor(active&&expanded);
        completeHiddenAnswer();
    }
    private void wakeOrbAnimation(){
        if(closed||!isShowing()||attachedWindow!=null&&!attachedWindow.isActive())return;
        motion.setDelay(16);
        if(!motion.isRunning()){lastTick=System.nanoTime();motion.start();}
    }
    private void completeHiddenAnswer(){
        if(closed||completedAnswer==null||expanded&&isShowing()&&(attachedWindow==null||attachedWindow.isActive()))return;
        // The worker has already saved the result. Hidden views need no token replay
        // or fade timer to release the completed operation.
        pending.set(null);reveal.reset();answerBubble.finish(completedAnswer);
        completedAnswer=null;revealTimer.stop();status.setText(completionStatus);finishBusy();
    }
    @Override public boolean contains(int x,int y){return isVisible()&&
        (card.isVisible()&&card.getBounds().contains(x,y)||orb.contains(x-orb.getX(),y-orb.getY()));}
    @Override public Component getComponentAt(int x,int y){
        // Closing pixels consume clicks without dispatching to the frozen chat controls.
        if((!expanded||opening<1||contentOpening<1)&&card.isVisible()&&card.getBounds().contains(x,y))return this;
        return super.getComponentAt(x,y);
    }
    private float visualProgress(){return opening*opening*(3-2*opening);}
    @Override protected void paintComponent(Graphics graphics){
        super.paintComponent(graphics);
        if(orb.isVisible()){
            double radius=24+15d*hoverAmount+11;
            // Paint in the parent so the enlarged shadow is not clipped to the 80px button component.
            Graphics2D shadow=(Graphics2D)graphics.create();
            try{
                shadow.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
                AffineTransform placement=AffineTransform.getTranslateInstance(orb.getX()+178+ORB_HINT_PADDING-radius,orb.getY()+43-radius);
                placement.scale(radius*2/ORB_SHADOW.getWidth(),radius*2/ORB_SHADOW.getHeight());
                shadow.drawImage(ORB_SHADOW,placement,null);
            }finally{shadow.dispose();}
        }
        Rectangle cardShadow=new Rectangle(card.getBounds());cardShadow.grow(21,30);
        if(card.isVisible()&&graphics.hitClip(cardShadow.x,cardShadow.y,cardShadow.width,cardShadow.height)){
            Graphics2D g=(Graphics2D)graphics.create();g.setComposite(AlphaComposite.SrcOver.derive(visualProgress()));
            dev.synesis.poc.ui.MistWorkspaceTheme.paintAssistantShadow(g,card.getBounds());g.dispose();
        }
    }
    private void layoutOrb(){
        if(orbCenter==null)orb.setBounds(Math.max(0,getWidth()-236)-ORB_HINT_PADDING,Math.max(0,getHeight()-88),358+ORB_HINT_PADDING*2,80);
        else {orbCenter.x=clampPosition(orbCenter.x,34,getWidth()-34);orbCenter.y=clampPosition(orbCenter.y,34,getHeight()-34);orb.setBounds(orbCenter.x-178-ORB_HINT_PADDING,orbCenter.y-40,358+ORB_HINT_PADDING*2,80);}
    }
    @Override public void doLayout(){
        layoutOrb();
        int width=Math.min(MAX_CARD_WIDTH,Math.min(requestedCardWidth,Math.max(1,getWidth()-32)));
        int height=Math.min(MAX_CARD_HEIGHT,Math.min(requestedCardHeight,Math.max(1,getHeight()-112)));
        if(width!=card.getWidth()||height!=card.getHeight())card.releaseSnapshot();
        Point placement=dev.synesis.poc.ui.FloatingChatPlacement.place(getWidth(),getHeight(),width,height,orbCenter,cardAnchor);
        int x=placement.x;cardBaseY=placement.y;
        int y=cardBaseY+(int)((1-visualProgress())*12);
        if(!resizing&&expanded&&opening==1&&contentOpening==1&&isShowing()&&!Boolean.getBoolean("synesis.reduceMotion")
                &&card.getWidth()==width&&card.getHeight()==height){
            if(card.getX()!=x||card.getY()!=y){
                if(cardMoveTarget==null){cardMoveX=card.getX();cardMoveY=card.getY();}
                cardMoveTarget=new Point(x,y);motion.setDelay(16);
            }else cardMoveTarget=null;
        }else{cardMoveTarget=null;card.setBounds(x,y,width,height);}
        layoutResizeGrip();
    }
    private void advanceCardPosition(float seconds){
        if(cardMoveTarget==null)return;
        Rectangle before=card.getBounds();
        double blend=1-Math.exp(-seconds/.065);
        cardMoveX+=(cardMoveTarget.x-cardMoveX)*blend;
        cardMoveY+=(cardMoveTarget.y-cardMoveY)*blend;
        if(Math.abs(cardMoveTarget.x-cardMoveX)<.5&&Math.abs(cardMoveTarget.y-cardMoveY)<.5){
            cardMoveX=cardMoveTarget.x;cardMoveY=cardMoveTarget.y;cardMoveTarget=null;
            if(!resizing&&enteringUser==null&&(answerBubble==null||answerBubble.arrivalStarted==0))motion.setDelay(33);
        }
        card.setLocation((int)Math.round(cardMoveX),(int)Math.round(cardMoveY));
        layoutResizeGrip();Rectangle damage=before.union(card.getBounds());damage.grow(24,24);repaint(damage);
    }
    private static int clampPosition(int value,int minimum,int maximum){return Math.max(0,Math.max(Math.min(minimum,maximum),Math.min(maximum,value)));}
    private void layoutResizeGrip(){
        resizeGrip.setBounds(card.getX()+2,card.getY()+2,14,14);
        boolean visible=card.isVisible()&&expanded&&opening==1&&contentOpening==1;
        resizeGrip.setVisible(visible);
        resizeGripSE.setBounds(card.getX()+card.getWidth()-16,card.getY()+card.getHeight()-16,14,14);
        resizeGripSE.setVisible(visible);
    }
    private void applyPendingResize(){
        if(!resizePending)return;resizePending=false;
        Rectangle before=card.getBounds();doLayout();
        Rectangle after=card.getBounds();
        if(before.equals(after))return;
        Rectangle damage=before.union(after);
        if(resizeOrbStart!=null){
            Rectangle oldOrb=orb.getBounds();
            orbCenter=new Point(resizeOrbStart.x+after.x+after.width-resizeCornerStart.x,
                resizeOrbStart.y+after.y+after.height-resizeCornerStart.y);
            layoutOrb();
            if(!oldOrb.equals(orb.getBounds()))damage=damage.union(oldOrb).union(orb.getBounds());
        }
        damage.grow(22,30);
        card.revalidate();repaint(damage);
    }
    private void toggle(){
        cardMoveTarget=null;
        expanded=!expanded;
        if(expanded){card.releaseSnapshot();if(!card.isVisible()){opening=0;contentOpening=0;}card.setVisible(true);}
        else {finishSendEntrance();if(answerBubble!=null){answerBubble.arrivalStarted=0;answerBubble.releaseArrival();}card.captureSnapshot();}
        motion.setDelay(16);refreshAnimation();doLayout();repaintCard();orb.repaint();
        if(expanded){load();SwingUtilities.invokeLater(()->input.requestFocusInWindow());}
    }
    private void repaintCard(){Rectangle damage=card.getBounds();damage.grow(21,30);repaint(damage);}
    private void advanceCard(float seconds){
        if(!card.isVisible())return;
        float target=expanded?1:0;
        if(opening==target&&(!expanded||contentOpening==1))return;
        boolean backgroundReady=opening==1;
        opening=expanded?Math.min(1,opening+seconds/.20f):Math.max(0,opening-seconds/.18f);
        // Start the contents on a later frame, after the background has fully appeared.
        if(expanded&&backgroundReady)contentOpening=Math.min(1,contentOpening+seconds/.16f);
        // Move the fixed-size surface, never relayout its Markdown/text on animation frames.
        Rectangle damage=card.getBounds();card.setLocation(card.getX(),cardBaseY+(int)((1-visualProgress())*12));
        damage=damage.union(card.getBounds());damage.grow(21,21);repaint(damage);
        if(opening==target&&(!expanded||contentOpening==1)){motion.setDelay(33);card.releaseContentSnapshot();if(!expanded){card.setVisible(false);card.releaseSnapshot();}}
        layoutResizeGrip();
    }
    private void load(){
        if(loaded)return;loadConversation(null,30);
    }
    private void loadConversation(String selected,int visible){
        if(busy||loadingConversation)return;boolean wasReady=ready,switching=selected!=null&&!selected.equals(session),older=selected!=null&&selected.equals(session)&&visible>visibleHistoryTurns;
        loadingConversation=true;loaded=true;ready=false;send.setEnabled(false);fresh.setEnabled(false);history.setEnabled(false);settings.setEnabled(false);
        worker.execute(()->{
            JsonObject saved=null;String error=null;
            try{saved=selected==null?conversations.current():conversations.load(selected);}
            catch(Exception failure){error="대화 기록을 읽지 못했어요. 원본은 보존했어요.";}
            java.util.Map<Long,java.util.List<AssistantAttachments.Item>> restoredImages=new java.util.HashMap<>();
            if(saved!=null&&error==null&&saved.has("imageHistory")){
                JsonArray turns=AssistantConversations.turns(saved);JsonObject history=saved.getAsJsonObject("imageHistory");
                for(int i=Math.max(0,turns.size()-visible);i<turns.size();i++)try{
                    long at=turns.get(i).getAsJsonObject().get("timestampMs").getAsLong();String key=Long.toString(at);if(!history.has(key))continue;
                    java.util.List<String> paths=new java.util.ArrayList<>();history.getAsJsonArray(key).forEach(p->paths.add(p.getAsString()));
                    restoredImages.put(at,AssistantAttachments.restore(folder,paths));
                }catch(Exception ignored){}
            }
            if(saved!=null&&error==null&&selected!=null)try{conversations.select(selected);}catch(Exception failure){error="대화 기록을 열지 못했어요. 원본은 보존했어요.";}
            JsonObject state=saved;String failure=error;
            SwingUtilities.invokeLater(()->{
                if(closed)return;
                loadingConversation=false;
                if(failure!=null){loaded=wasReady;ready=wasReady;send.setEnabled(wasReady&&!attachments.loading());fresh.setEnabled(wasReady);history.setEnabled(wasReady);settings.setEnabled(wasReady);status.setText(failure);return;}
                if(state!=null){
                    finishSendEntrance();if(answerBubble!=null)answerBubble.releaseArrival();answerBubble=null;
                    receipts=state.has("receipts")?state.getAsJsonObject("receipts"):new JsonObject();imageHistory=state.has("imageHistory")?state.getAsJsonObject("imageHistory"):new JsonObject();deliveryHistory=state.has("deliveryHistory")?state.getAsJsonObject("deliveryHistory"):new JsonObject();memory=state.getAsJsonObject("memory");session=state.get("sessionId").getAsString();messages.removeAll();
                    visibleHistoryTurns=visible;JsonArray turns=AssistantConversations.turns(state);int start=Math.max(0,turns.size()-visible);
                    if(start>0){JButton more=new AssistantButton("이전 메시지 더 보기 ("+start+"개)");styleButton(more,false);more.setAlignmentX(LEFT_ALIGNMENT);more.addActionListener(e->loadConversation(session,visibleHistoryTurns+30));messages.add(more);messages.add(Box.createVerticalStrut(10));}
                    restoringHistory=true;
                    try{for(int i=start;i<turns.size();i++){
                        JsonObject turn=turns.get(i).getAsJsonObject();ChatBubble restoredUser=addBubble(turn.get("question").getAsString(),true,restoredImages.getOrDefault(turn.has("timestampMs")?turn.get("timestampMs").getAsLong():0L,java.util.List.of()));
                        if(turn.has("timestampMs")){String key=turn.get("timestampMs").getAsString();if(deliveryHistory.has(key))restoredUser.received(deliveryHistory.get(key).getAsLong());}
                        JsonArray updates=AssistantActivityLog.fromTurn(turn);
                        if(turn.get("answer").getAsString().isBlank()&&updates.isEmpty())continue;
                        ChatBubble restored=addBubble("",false);restored.restoreActivity(updates);restored.finish(turn.get("answer").getAsString());
                        if(turn.has("timestampMs")){long at=turn.get("timestampMs").getAsLong();restored.metadata(receipts.has(Long.toString(at))?receipts.get(Long.toString(at)).getAsString():"크레딧 확인 중",at);}
                    }}finally{restoringHistory=false;}
                    if(messages.getComponentCount()==0)welcome();
                }
                if(switching){input.setText("");attachments.clear();status.setText("이전 대화를 열었어요 · 이어서 대화할 수 있어요");}
                ready=true;send.setEnabled(!attachments.loading());fresh.setEnabled(true);history.setEnabled(true);settings.setEnabled(true);messages.revalidate();scrollBottom();
                if(older)SwingUtilities.invokeLater(()->scroll.getVerticalScrollBar().setValue(0));
            });
        });
    }
    private void welcome(){messages.removeAll();addBubble("안녕하세요! 학습과 일상을 돕는 나만의 비서에요.\n자료를 정리하고, 일정을 계획하고, 해야 할 일을 챙겨 보세요.\n필요한 작업은 제가 도와드릴게요.\n이렇게 말해 보세요!\n“내일 오후 2시 중간고사 일정 추가해줘.”\n\"홈화면 파일들 과목별로 분류해서 폴더에 정리해줘.\"",false);}
    private void showConversations(){
        if(busy||!ready||!expanded)return;history.setEnabled(false);
        worker.execute(()->{
            try{
                java.util.List<AssistantConversations.Entry> entries=conversations.list();
                SwingUtilities.invokeLater(()->{
                    if(closed)return;history.setEnabled(!busy);if(busy||!expanded||!history.isShowing())return;
                    JPopupMenu popup=new JPopupMenu();
                    if(entries.isEmpty()){
                        JMenuItem empty=new JMenuItem("저장된 대화가 아직 없어요");empty.setEnabled(false);popup.add(empty);
                    }else{
                        JList<AssistantConversations.Entry> list=new JList<>(entries.toArray(AssistantConversations.Entry[]::new));
                        list.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);list.setBackground(Color.WHITE);list.setFixedCellHeight(57);
                        list.setCellRenderer((owner,item,index,selected,focus)->{
                            JPanel row=new JPanel(new BorderLayout(0,4));
                            Color divider=index+1<owner.getModel().getSize()?RoundedPopupMenuUI.DIVIDER:Color.WHITE;
                            row.setBorder(BorderFactory.createCompoundBorder(
                                selected?BorderFactory.createLineBorder(Color.GRAY,1,true):BorderFactory.createMatteBorder(0,0,1,0,divider),
                                selected?BorderFactory.createEmptyBorder(7,11,7,11):BorderFactory.createEmptyBorder(8,12,7,12)));
                            row.setBackground(Color.WHITE);
                            JLabel title=new JLabel();title.putClientProperty("html.disable",true);title.setText((item.id().equals(session)?"● ":"")+item.title());title.setFont(LibraryDesign.medium(12));title.setForeground(AssistantChatTheme.TEXT);
                            String date=item.updatedAt()>0?java.time.format.DateTimeFormatter.ofPattern("MM/dd HH:mm").withZone(ZoneId.of("Asia/Seoul")).format(Instant.ofEpochMilli(item.updatedAt())):"";
                            JLabel detail=new JLabel(date+" · 메시지 "+item.turns()+"개");detail.setFont(LibraryDesign.medium(10));detail.setForeground(AssistantChatTheme.MUTED);row.add(title);row.add(detail,BorderLayout.SOUTH);return row;
                        });
                        for(int i=0;i<entries.size();i++)if(entries.get(i).id().equals(session)){list.setSelectedIndex(i);break;}
                        Runnable choose=()->{AssistantConversations.Entry entry=list.getSelectedValue();if(entry==null)return;popup.setVisible(false);loadConversation(entry.id(),30);};
                        list.addMouseListener(new MouseAdapter(){@Override public void mouseClicked(MouseEvent e){int index=list.locationToIndex(e.getPoint());if(SwingUtilities.isLeftMouseButton(e)&&index>=0&&list.getCellBounds(index,index).contains(e.getPoint()))choose.run();}});
                        list.getInputMap().put(KeyStroke.getKeyStroke("ENTER"),"choose");list.getActionMap().put("choose",new AbstractAction(){public void actionPerformed(ActionEvent e){choose.run();}});
                        JScrollPane picker=new dev.synesis.poc.ui.SmoothScrollPane(list);picker.setBorder(null);picker.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);picker.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
                        picker.setPreferredSize(new Dimension(Math.min(360,card.getWidth()-40),Math.min(342,entries.size()*57)));popup.add(picker);
                        SwingUtilities.invokeLater(list::requestFocusInWindow);
                    }
                    popup.show(history,Math.min(0,history.getWidth()-popup.getPreferredSize().width),history.getHeight()+4);
                });
            }catch(Exception failure){SwingUtilities.invokeLater(()->{if(!closed){history.setEnabled(!busy);status.setText("대화 목록을 읽지 못했어요. 원본은 보존했어요.");}});}
        });
    }
    private void showPreferences(){
        if(busy||!ready||!expanded)return;settings.setEnabled(false);
        worker.execute(()->{
            try{
                AssistantLocal.PreferencesDebug snapshot=local.preferencesDebug();
                SwingUtilities.invokeLater(()->{
                    if(closed)return;settings.setEnabled(ready&&!busy);
                    if(busy||!expanded||!settings.isShowing())return;
                    JPopupMenu popup=new JPopupMenu();popup.add(new AssistantPreferencesPanel(snapshot,Math.min(620,card.getWidth()-40)));
                    popup.show(settings,Math.min(0,settings.getWidth()-popup.getPreferredSize().width),settings.getHeight()+4);
                });
            }catch(Exception failure){SwingUtilities.invokeLater(()->{if(!closed){settings.setEnabled(ready&&!busy);status.setText("사용자 맞춤 지침을 읽지 못했어요. 원본은 보존했어요.");}});}
        });
    }
    private void resetConversation(){
        if(busy||!ready||!expanded)return;JsonObject empty=new JsonObject();empty.addProperty("documentId","home-assistant-v1");empty.add("turns",new JsonArray());
        visibleHistoryTurns=30;memory=empty;receipts=new JsonObject();imageHistory=new JsonObject();deliveryHistory=new JsonObject();attachments.clear();session=UUID.randomUUID().toString();welcome();status.setText("새 대화를 시작했어요 · 개인화 메모리는 유지돼요");persist(memory.deepCopy(),session);
    }
    private void persist(JsonObject state,String id){worker.execute(()->{try{save(state,id);}catch(Exception failure){SwingUtilities.invokeLater(()->status.setText("대화 기록 저장에 실패했어요"));}});}
    private void save(JsonObject state,String id)throws Exception{
        save(state,id,null);
    }
    private void save(JsonObject state,String id,JsonObject fullTurn)throws Exception{
        Files.createDirectories(folder);JsonObject saved=new JsonObject();saved.addProperty("sessionId",id);saved.add("memory",state);saved.add("receipts",receipts.deepCopy());saved.add("imageHistory",imageHistory.deepCopy());saved.add("deliveryHistory",deliveryHistory.deepCopy());
        if(fullTurn!=null){JsonArray transcript=state.getAsJsonArray("turns").deepCopy();transcript.set(transcript.size()-1,fullTurn);saved.add("transcript",transcript);}
        conversations.save(saved);
    }
    private ChatReplyControl replyControl;
    private Timer preparingBubbleTimer;
    private void stopPreparingBubble(){
        if(preparingBubbleTimer==null)return;
        preparingBubbleTimer.stop();
        preparingBubbleTimer=null;
    }
    private boolean currentReply(ChatReplyControl reply){
        return !closed&&busy&&replyControl==reply&&!reply.cancelled();
    }
    private void uploaded(ChatReplyControl reply,ChatBubble sentBubble,long at){
        if(!currentReply(reply))return;
        if(enteringUser==sentBubble)finishSendEntrance();
        sentBubble.received(at,true);
        if(!answerBubble.awaitingServer)return;
        status.setText("비서가 답변을 준비하고 있어요…");
        stopPreparingBubble();
        preparingBubbleTimer=new Timer(PREPARING_BUBBLE_DELAY_MS,event->{
            if(currentReply(reply)&&answerBubble.awaitingServer)answerBubble.serverArrived();
        });
        preparingBubbleTimer.setRepeats(false);
        preparingBubbleTimer.start();
    }
    private void displayReplyText(ChatReplyControl reply,String text){
        if(!currentReply(reply)||text.isBlank())return;
        stopPreparingBubble();
        pending.set(text);
        if(!answerBubble.waiting)return;
        if(enteringUser!=null)finishSendEntrance();
        if(answerBubble.arrivalStarted>0){
            answerBubble.arrivalStarted=0;
            answerBubble.releaseArrival();
        }
        answerBubble.serverArrived(false);
        reveal();
    }
    private Icon sendIcon;
    private void updateSendButton(){
        if(sendIcon==null)sendIcon=send.getIcon();
        send.setIcon(busy?ChatReplyControl.stopIcon():sendIcon);
        send.setToolTipText(busy?"답변 생성 중지":"메시지 보내기");
        send.getAccessibleContext().setAccessibleName(busy?"답변 생성 중지":"메시지 보내기");
        send.setEnabled(ready&&(busy?replyControl!=null&&!replyControl.cancelled():!attachmentsLoading()));
    }
    private void finishCompletedReply(){
        finishSendEntrance();answerBubble.arrivalStarted=0;answerBubble.releaseArrival();answerBubble.awaitingServer=false;
        answerBubble.setVisible(true);if(answerBubble.gapAfter!=null)answerBubble.gapAfter.setVisible(true);
        pending.set(null);reveal.reset();revealTimer.stop();answerBubble.finish(completedAnswer);
        completedAnswer=null;status.setText(completionStatus);finishBusy();messages.revalidate();scrollBottom();
    }
    private void cancelReply(){
        if(!busy)return;
        if(completedAnswer!=null){finishCompletedReply();return;}
        if(replyControl==null)return;
        stopPreparingBubble();
        replyControl.cancel();updateSendButton();
        finishSendEntrance();answerBubble.arrivalStarted=0;answerBubble.releaseArrival();revealTimer.stop();pending.set(null);reveal.reset();
        answerBubble.stopThinking();
        if(answerBubble.activityText.isEmpty()){
            answerBubble.setVisible(false);if(answerBubble.gapAfter!=null)answerBubble.gapAfter.setVisible(false);
        }
        messages.revalidate();messages.repaint();
    }
    private void removeCancelledReply(){
        finishSendEntrance();answerBubble.arrivalStarted=0;answerBubble.releaseArrival();revealTimer.stop();pending.set(null);reveal.reset();completedAnswer=null;
        messages.remove(answerBubble);if(answerBubble.gapAfter!=null)messages.remove(answerBubble.gapAfter);
        answerBubble=null;status.setText(" ");finishBusy();messages.revalidate();messages.repaint();
    }
    private JsonObject saveInterruptedTurn(JsonObject request,String question,JsonArray images,long readAt,JsonArray updates,String answer)throws Exception{
        long at=System.currentTimeMillis();
        JsonObject turn=new JsonObject();turn.addProperty("question",question);turn.addProperty("answer",answer);turn.addProperty("timestampMs",at);
        turn.add("activity",updates.deepCopy());
        JsonArray transcript=new JsonArray();transcript.add(turn);
        if(readAt>0)deliveryHistory.addProperty(Long.toString(at),readAt);
        if(!images.isEmpty())imageHistory.add(Long.toString(at),images.deepCopy());
        JsonObject snapshot=new JsonObject();snapshot.addProperty("sessionId",request.get("sessionId").getAsString());
        JsonObject next=request.getAsJsonObject("memory").deepCopy();
        if(!answer.isBlank())next.getAsJsonArray("turns").add(turnForMemory(turn));
        snapshot.add("memory",next);snapshot.add("transcript",transcript);
        snapshot.add("receipts",receipts.deepCopy());snapshot.add("imageHistory",imageHistory.deepCopy());snapshot.add("deliveryHistory",deliveryHistory.deepCopy());
        conversations.save(snapshot);
        return next;
    }
    private static JsonObject turnForMemory(JsonObject turn){
        JsonObject out=new JsonObject();
        for(String key:new String[]{"question","answer","timestampMs"})out.add(key,turn.get(key).deepCopy());
        return out;
    }
    private void finishInterruptedReply(String message){
        finishSendEntrance();answerBubble.arrivalStarted=0;answerBubble.releaseArrival();
        pending.set(null);reveal.reset();revealTimer.stop();completedAnswer=null;
        answerBubble.awaitingServer=false;answerBubble.setVisible(true);
        if(answerBubble.gapAfter!=null)answerBubble.gapAfter.setVisible(true);
        answerBubble.finish(message);finishBusy();messages.revalidate();messages.repaint();
    }
    private void send(){
        String typed=input.getText().strip();if(busy||!ready||!expanded||!send.isEnabled()||attachments.loading()||typed.isEmpty()&&attachments.empty()||closed)return;
        String question=typed.isEmpty()?"첨부한 이미지를 확인하고 설명해 주세요.":typed;
        java.util.List<AssistantAttachments.Item> sentImages=attachments.take();
        ChatReplyControl reply=new ChatReplyControl();AssistantActivityLog updates=new AssistantActivityLog();replyControl=reply;busy=true;updateSendButton();fresh.setEnabled(false);history.setEnabled(false);settings.setEnabled(false);input.setText("");
        ChatBubble sentBubble=addBubble(question,true,sentImages);java.util.concurrent.atomic.AtomicLong readAt=new java.util.concurrent.atomic.AtomicLong();answerBubble=addBubble("",false);answerBubble.thinking();status.setText("메시지를 보내고 있어요…");
        startSendEntrance(sentBubble,answerBubble);
        reveal.reset();completedAnswer=null;pending.set(null);refreshAnimation();
        JsonObject request=new JsonObject();request.addProperty("question",question);request.add("memory",memory.deepCopy());
        request.addProperty("assistantProtocol","synesis.assistant.v1");
        request.addProperty("assistantPresentation",2);
        request.addProperty("sessionId",session);
        request.addProperty("turnId",UUID.randomUUID().toString());request.addProperty("localDateTime",ZonedDateTime.now().toString());
        request.addProperty("timezone",ZoneId.systemDefault().getId());
        JsonArray imagePaths=new JsonArray();sentImages.forEach(item->imagePaths.add(item.path()));request.add("attachments",imagePaths);
        local.begin(session,request.get("turnId").getAsString(),typed,memory.getAsJsonArray("turns"));
        worker.execute(()->{
            try(PdfProcess operation=new PdfProcess()){
                process=operation;if(closed)return;
                SubscriptionUsage.activate(PdfLibraryStore.defaultRoot());
                Files.createDirectories(folder.resolve("requests"));Path file=folder.resolve("requests").resolve(request.get("turnId").getAsString()+".json");
                Files.writeString(file,new Gson().toJson(request));
                operation.run("home_assistant.py",java.util.List.of("--request",file.toString()),operation.ticket(),event->{
                    if(event.has("type")&&event.get("type").getAsString().equals("assistant_progress")){
                        String phase=event.has("phase")?event.get("phase").getAsString():"";
                        if("status".equals(phase)&&event.has("text")){
                            String message=event.get("text").getAsString();
                            SwingUtilities.invokeLater(()->{if(currentReply(reply))status.setText(message);});
                        }else if("result".equals(phase))updates.accept(event);
                        return;
                    }
                    if(reply.cancelled())return;
                    String type=event.has("type")?event.get("type").getAsString():"";
                    if(type.equals("assistant_received")){
                        long at=event.get("timestampMs").getAsLong();
                        if(readAt.compareAndSet(0,at))SwingUtilities.invokeLater(()->uploaded(reply,sentBubble,at));
                    }
                    if(type.equals("assistant_delta")){
                        String delta=event.get("text").getAsString();
                        if(!delta.isBlank())SwingUtilities.invokeLater(()->displayReplyText(reply,delta));
                    }
                    if(type.equals("assistant_stage")){
                        String stage=event.get("stage").getAsString();
                        SwingUtilities.invokeLater(()->{if(!closed&&busy&&replyControl==reply&&!reply.cancelled()){
                            if(stage.equals("searching"))status.setText("웹에서 자료를 확인하고 있어요…");
                        }});
                    }
                },local::handle,reply);
                JsonObject result=JsonParser.parseString(Files.readString(file.resolveSibling(file.getFileName().toString().replace(".json",".result.json")))).getAsJsonObject();
                JsonObject next=result.getAsJsonObject("memory");
                local.finish(result.get("answer").getAsString());
                JsonObject usageResult=result.getAsJsonObject("runUsage");
                String finalCost=usageResult.get("unknownUsageRequests").getAsInt()>0?"사용량 정산 확인 중":String.format(java.util.Locale.ROOT,"%.2f 크레딧",usageResult.get("usageBasedUsd").getAsDouble()*1400/2.3);
                JsonArray turns=next.getAsJsonArray("turns");long answeredAt=System.currentTimeMillis();turns.get(turns.size()-1).getAsJsonObject().addProperty("timestampMs",answeredAt);
                synchronized(this){receipts.addProperty(Long.toString(answeredAt),finalCost);if(readAt.get()>0)deliveryHistory.addProperty(Long.toString(answeredAt),readAt.get());if(!imagePaths.isEmpty())imageHistory.add(Long.toString(answeredAt),imagePaths.deepCopy());}
                JsonObject fullTurn=turns.get(turns.size()-1).getAsJsonObject().deepCopy();fullTurn.addProperty("question",question);fullTurn.addProperty("answer",result.get("answer").getAsString());
                String storageWarning=null;try{save(next,session,fullTurn);}catch(Exception failure){storageWarning=" · 대화 저장 실패";}
                String warning=storageWarning;
                SwingUtilities.invokeLater(()->{
                    if(closed||replyControl!=reply)return;dataChanged.run();answerBubble.metadata(finalCost,answeredAt);memory=next;completedAnswer=result.get("answer").getAsString();pending.set(completedAnswer);
                    JsonObject usage=result.getAsJsonObject("runUsage");
                    completionStatus=(usage.get("unknownUsageRequests").getAsInt()>0?"사용량 정산 확인 중":String.format(java.util.Locale.ROOT,"이번 답변 %.2f 크레딧",usage.get("usageBasedUsd").getAsDouble()*1400/2.3))+(warning==null?"":warning);
                    status.setText("답변을 정리하고 있어요…"+(warning==null?"":warning));
                    if(reply.cancelled())finishCompletedReply();
                    else{displayReplyText(reply,completedAnswer);completeHiddenAnswer();}
                });
            }catch(Exception failure){
                JsonArray confirmed=updates.snapshot();
                if(failure instanceof ChatReplyControl.Cancelled){
                    String warning=null;JsonObject next=null;
                    String stopped=confirmed.isEmpty()?"":"요청을 중지했어요. 위에서 처리된 결과를 확인할 수 있어요.";
                    String notice=local.failureNotice();
                    if(!notice.isBlank())stopped=(stopped.isBlank()?"요청을 중지했어요.":stopped)+"\n"+notice;
                    try{next=saveInterruptedTurn(request,question,imagePaths,readAt.get(),confirmed,stopped);}catch(Exception storage){warning="대화 저장을 완료하지 못했어요.";}
                    String storageWarning=warning;
                    String stoppedAnswer=stopped;JsonObject savedMemory=next;
                    SwingUtilities.invokeLater(()->{if(!closed&&replyControl==reply){
                        if(savedMemory!=null)memory=savedMemory;
                        if(stoppedAnswer.isBlank())removeCancelledReply();
                        else{answerBubble.restoreActivity(confirmed);finishInterruptedReply(stoppedAnswer);}
                        if(storageWarning!=null)status.setText(storageWarning);
                    }});
                    return;
                }
                String notice=local.failureNotice();
                String failureAnswer="요청을 마무리하지 못했어요."+(notice.isEmpty()?"":"\n"+notice);
                JsonObject next=null;String storageWarning="";
                if(!confirmed.isEmpty()||!notice.isBlank())try{next=saveInterruptedTurn(request,question,imagePaths,readAt.get(),confirmed,failureAnswer);}
                catch(Exception storage){storageWarning=" · 대화 저장 실패";}
                JsonObject savedMemory=next;String warning=storageWarning;
                SwingUtilities.invokeLater(()->{
                if(closed||replyControl!=reply)return;revealTimer.stop();pending.set(null);
                if(savedMemory!=null)memory=savedMemory;
                answerBubble.metadata("크레딧 확인 필요",answerBubble.answeredAt);
                answerBubble.restoreActivity(confirmed);
                finishInterruptedReply(failureAnswer);
                status.setText("자동 재전송하지 않아요"+warning);
            });}finally{process=null;}
        });
    }
    private void reveal(){
        // Keep the landing position fixed until the sent bubble has arrived.
        // API streaming continues into pending while only visual replay waits.
        if(answerBubble==null||replyControl!=null&&replyControl.cancelled()||enteringUser!=null||answerBubble.arrivalStarted>0)return;
        String text=pending.getAndSet(null);if(text!=null&&!text.isBlank())reveal.accept(text);
        if(!reveal.complete()){
            boolean follow=nearBottom();answerBubble.stream(reveal.advance());
            if(completedAnswer==null)status.setText("개인 학습 에이전트가 답변하고 있어요…");
            messages.revalidate();if(follow)scrollBottom();
        }
        if(completedAnswer!=null&&reveal.complete()&&pending.get()==null
                &&answerBubble.shown.equals(answerBubble.markdownSource)
                &&!answerBubble.streamFade.active(System.currentTimeMillis())){
            boolean follow=nearBottom();answerBubble.finish(completedAnswer);completedAnswer=null;revealTimer.stop();
            status.setText(completionStatus);finishBusy();if(follow)scrollBottom();
        }
    }
    private boolean attachmentsLoading(){return attachments!=null&&attachments.loading();}
    private void attachmentChanged(){if(composer!=null)composer.refresh();updateSendButton();}
    private void finishBusy(){stopPreparingBubble();busy=false;replyControl=null;updateSendButton();fresh.setEnabled(true);history.setEnabled(true);settings.setEnabled(true);}
    private void openAnswerLink(String link){
        try{java.net.URI uri=java.net.URI.create(link);
            if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getHost()==null||!Desktop.isDesktopSupported())return;
            worker.execute(()->{try{Desktop.getDesktop().browse(uri);}catch(Exception e){SwingUtilities.invokeLater(()->status.setText("링크를 열지 못했어요."));}});
        }catch(IllegalArgumentException ignored){}
    }
    private boolean nearBottom(){JScrollBar bar=scroll.getVerticalScrollBar();return bar.getValue()+bar.getVisibleAmount()>=bar.getMaximum()-48;}
    private void scrollBottom(){if(bottomScrollPending)return;bottomScrollPending=true;SwingUtilities.invokeLater(()->{bottomScrollPending=false;if(answerBubble!=null&&answerBubble.arrivalStarted>0)return;JScrollBar bar=scroll.getVerticalScrollBar();bar.setValue(bar.getMaximum());});}
    private ChatBubble addBubble(String text,boolean user){return addBubble(text,user,java.util.List.of());}
    private ChatBubble addBubble(String text,boolean user,java.util.List<AssistantAttachments.Item> images){ChatBubble bubble=new ChatBubble(text,user);if(!images.isEmpty())bubble.addImages(images);messages.add(bubble);bubble.gapAfter=Box.createVerticalStrut(10);messages.add(bubble.gapAfter);while(!restoringHistory&&visibleHistoryTurns<=30&&messages.getComponentCount()>120){messages.remove(0);messages.remove(0);}messages.revalidate();scrollBottom();return bubble;}
    private void animate(){
        long now=System.nanoTime();float dt=Math.min(.1f,(now-lastTick)/1_000_000_000f);lastTick=now;
        applyPendingResize();
        if(resizing)motion.setDelay(16);
        float previousHover=hoverAmount;
        Rectangle previousHint=orb.hintBounds();
        hoverAmount=HoverMotion.advance(hoverAmount,hover,dt);
        if(hoverAmount!=previousHover)repaint(orb.getX()+124+ORB_HINT_PADDING,orb.getY()-11,108,108);
        advanceCard(dt);
        advanceCardPosition(dt);
        if(enteringUser!=null){
            if(entranceProgress()>=1)finishSendEntrance();
            else {
                Rectangle damage=entranceDamage==null?new Rectangle():new Rectangle(entranceDamage);
                Point p=SwingUtilities.convertPoint(enteringUser,0,0,card);
                damage=damage.union(new Rectangle(p.x,p.y,enteringUser.getWidth(),enteringUser.getHeight()));
                Point inputOrigin=SwingUtilities.convertPoint(composer,0,0,card);
                damage=damage.union(new Rectangle(inputOrigin.x,inputOrigin.y,composer.getWidth(),composer.getHeight()));
                if(enteringAnswer!=null){Point a=SwingUtilities.convertPoint(enteringAnswer,0,0,card);damage=damage.union(new Rectangle(a.x,a.y,enteringAnswer.getWidth(),enteringAnswer.getHeight()));}
                // Include the next frame's spring overshoot, not only the last
                // painted bounds, so the enlarged leading edge cannot be clipped.
                damage.grow(48,24);card.repaint(damage);
            }
        }
        // The new portrait is static. Repaint the icon and hint only while hover changes.
        int radius=(int)Math.ceil(24+15*hoverAmount)+2;
        Rectangle orbDamage=new Rectangle(178+ORB_HINT_PADDING-radius,40-radius,radius*2,radius*2);
        if(!expanded&&hoverAmount!=previousHover)orbDamage=orbDamage.union(previousHint).union(orb.hintBounds());
        if(hoverAmount!=previousHover)orb.repaint(orbDamage);
        if(expanded)for(Component child:messages.getComponents())if(child instanceof ChatBubble bubble)bubble.advanceFade();
        if(busy&&expanded&&answerBubble!=null)answerBubble.animateText();
        boolean fast=hoverAmount!=(hover?1:0)||resizing||cardMoveTarget!=null||enteringUser!=null
            ||answerBubble!=null&&answerBubble.arrivalStarted>0||card.isVisible()&&(opening<1||contentOpening<1);
        motion.setDelay(fast?16:33);
        if(!fast&&!expanded&&!busy&&!card.isVisible())motion.stop();
    }
    @Override public void close(){stopPreparingBubble();if(answerBubble!=null)answerBubble.releaseArrival();finishSendEntrance();closed=true;connectivity.close();motion.stop();revealTimer.stop();PdfProcess active=process;if(active!=null)active.close();worker.shutdownNow();attachments.close();composer.dispose();card.releaseSnapshot();}
    private final class ChatCard extends JPanel{
        private java.awt.image.BufferedImage closingSnapshot;
        private java.awt.image.BufferedImage contentSnapshot;
        ChatCard(){setOpaque(false);}
        @Override public void doLayout(){
            // Assign final bounds once. BorderLayout followed by recentering used
            // to resize HTML/composer trees twice on every validation pass.
            Insets insets=getInsets();int available=Math.max(1,getWidth()-insets.left-insets.right);
            // Reach the 650px column and 24px gutters together at 698px.
            // Beyond that, keep the column fixed and center it in the extra space.
            int extra=(int)Math.round(8*Math.max(0,Math.min(1,(getWidth()-460)/238d)));
            int width=Math.max(1,Math.min(650,available-2*extra));
            int x=insets.left+(available-width)/2;
            BorderLayout layout=(BorderLayout)getLayout();
            Component north=layout.getLayoutComponent(BorderLayout.NORTH),south=layout.getLayoutComponent(BorderLayout.SOUTH);
            int top=insets.top,bottom=getHeight()-insets.bottom;
            if(north!=null&&north.isVisible()){
                int height=north.getPreferredSize().height;north.setBounds(x,top,width,height);top+=height+layout.getVgap();
            }
            if(south!=null&&south.isVisible()){
                int height=south.getPreferredSize().height;south.setBounds(x,bottom-height,width,height);bottom-=height+layout.getVgap();
            }
            // Nudge messages 6px right, keeping their width and the scrollbar's right edge fixed.
            int messageX=x+6;
            int scrollWidth=Math.max(1,getWidth()-6-messageX);
            int gutter=Math.max(0,scrollWidth-width+6);
            Insets viewportInsets=scroll.getViewportBorder()==null?new Insets(0,0,0,0):scroll.getViewportBorder().getBorderInsets(scroll);
            if(viewportInsets.right!=gutter)scroll.setViewportBorder(BorderFactory.createEmptyBorder(0,0,0,gutter));
            scroll.setBounds(messageX,top,scrollWidth,Math.max(0,bottom-top));
        }
        @Override protected boolean isPaintingOrigin(){return enteringUser!=null;}
        @Override public boolean isValidateRoot(){return true;}
        void releaseContentSnapshot(){if(contentSnapshot!=null){contentSnapshot.flush();contentSnapshot=null;}}
        void releaseSnapshot(){if(closingSnapshot!=null){closingSnapshot.flush();closingSnapshot=null;}releaseContentSnapshot();}
        void captureSnapshot(){
            if(closingSnapshot!=null||getWidth()<=0||getHeight()<=0)return;
            double scale=getGraphicsConfiguration()==null?1:Math.min(2,getGraphicsConfiguration().getDefaultTransform().getScaleX());
            closingSnapshot=new java.awt.image.BufferedImage((int)Math.ceil(getWidth()*scale),(int)Math.ceil(getHeight()*scale),java.awt.image.BufferedImage.TYPE_INT_ARGB);
            Graphics2D g=closingSnapshot.createGraphics();g.scale(scale,scale);paintComponent(g);paintChildren(g);g.dispose();
        }
        @Override protected void paintChildren(Graphics graphics){
            if(contentOpening<=0)return;
            if(contentOpening>=1){super.paintChildren(graphics);paintSendEntrance(graphics);if(answerBubble!=null)answerBubble.paintArrival(graphics);return;}
            if(contentSnapshot==null){
                double scale=getGraphicsConfiguration()==null?1:Math.min(2,getGraphicsConfiguration().getDefaultTransform().getScaleX());
                contentSnapshot=new java.awt.image.BufferedImage(Math.max(1,(int)Math.ceil(getWidth()*scale)),Math.max(1,(int)Math.ceil(getHeight()*scale)),java.awt.image.BufferedImage.TYPE_INT_ARGB);
                Graphics2D cache=contentSnapshot.createGraphics();cache.scale(scale,scale);super.paintChildren(cache);cache.dispose();
            }
            Graphics2D g=(Graphics2D)graphics.create();float alpha=contentOpening*contentOpening*(3-2*contentOpening);
            g.setComposite(AlphaComposite.SrcOver.derive(alpha));g.drawImage(contentSnapshot,0,0,getWidth(),getHeight(),null);g.dispose();
        }
        @Override protected void paintComponent(Graphics g){Graphics2D a=(Graphics2D)g.create();a.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);a.setColor(AssistantChatTheme.BACKGROUND);a.fillRoundRect(0,0,getWidth()-1,getHeight()-1,22,22);a.setColor(AssistantChatTheme.LINE);a.drawRoundRect(0,0,getWidth()-1,getHeight()-1,22,22);a.dispose();}
        @Override public void paint(Graphics g){Graphics2D a=(Graphics2D)g.create();a.setComposite(AlphaComposite.SrcOver.derive(visualProgress()));
            if(closingSnapshot!=null)a.drawImage(closingSnapshot,0,0,getWidth(),getHeight(),null);else super.paint(a);a.dispose();}
    }
    private static final int ORB_HINT_PADDING=32;
    // Fixed 96px alpha sprite (36 KiB), shared across all hover sizes; no blur or growing cache.
    private static final java.awt.image.BufferedImage ORB_SHADOW=createOrbShadow();
    private static java.awt.image.BufferedImage createOrbShadow(){
        java.awt.image.BufferedImage image=new java.awt.image.BufferedImage(96,96,java.awt.image.BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=image.createGraphics();
        try{
            g.setPaint(new RadialGradientPaint(48,48,48,new float[]{0,.56f,.72f,.88f,1},
                new Color[]{new Color(20,20,20,88),new Color(20,20,20,78),new Color(20,20,20,42),new Color(20,20,20,12),new Color(20,20,20,0)}));
            g.fillRect(0,0,96,96);
        }finally{g.dispose();}
        return image;
    }
    private final class Orb extends JComponent{
        @Override public javax.accessibility.AccessibleContext getAccessibleContext(){if(accessibleContext==null){accessibleContext=new AccessibleJComponent() {};accessibleContext.setAccessibleName("개인 학습 에이전트 채팅 열기");}return accessibleContext;}
        Orb(){setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));setFocusable(true);setToolTipText("개인 학습 에이전트 열기");
            MouseAdapter drag=new MouseAdapter(){
                private Point pressed,initial;private boolean moved;
                public void mouseEntered(MouseEvent e){hover=true;wakeOrbAnimation();}
                public void mouseExited(MouseEvent e){hover=false;wakeOrbAnimation();}
                public void mousePressed(MouseEvent e){if(!SwingUtilities.isLeftMouseButton(e))return;pressed=SwingUtilities.convertPoint(Orb.this,e.getPoint(),HomeAssistant.this);initial=new Point(getX()+178+ORB_HINT_PADDING,getY()+40);moved=false;}
                public void mouseDragged(MouseEvent e){
                    if(pressed==null)return;
                    Point current=SwingUtilities.convertPoint(Orb.this,e.getPoint(),HomeAssistant.this);
                    if(!moved&&pressed.distance(current)<5)return;
                    moved=true;Rectangle damage=card.getBounds().union(getBounds());
                    orbCenter=new Point(initial.x+current.x-pressed.x,initial.y+current.y-pressed.y);cardAnchor=null;
                    HomeAssistant.this.doLayout();damage=damage.union(card.getBounds()).union(getBounds());damage.grow(24,24);HomeAssistant.this.repaint(damage);e.consume();
                }
                public void mouseReleased(MouseEvent e){pressed=null;initial=null;}
                public void mouseClicked(MouseEvent e){if(SwingUtilities.isLeftMouseButton(e)&&!moved)toggle();}
            };addMouseListener(drag);addMouseMotionListener(drag);
            getInputMap(WHEN_FOCUSED).put(KeyStroke.getKeyStroke("SPACE"),"open");getInputMap(WHEN_FOCUSED).put(KeyStroke.getKeyStroke("ENTER"),"open");
            getActionMap().put("open",new AbstractAction(){public void actionPerformed(ActionEvent e){toggle();}});
        }
        private Rectangle hintBounds(){
            // Share the orb's eased hover progress; grow and slide away from its center.
            double scale=1+.10*hoverAmount;
            int width=(int)Math.ceil(132*scale),height=(int)Math.ceil(34*scale);
            boolean left=getX()+ORB_HINT_PADDING+7>=8;
            int travel=Math.round(14*hoverAmount);
            int preferred=getX()+ORB_HINT_PADDING+(left?7-travel-(width-132):218+travel);
            int x=clampPosition(preferred,8,HomeAssistant.this.getWidth()-width-8)-getX();
            return new Rectangle(x,40-height/2,width,height);
        }
        @Override public boolean contains(int x,int y){return Point2D.distance(x,y,178+ORB_HINT_PADDING,40)<=Math.max(34,24+15*hoverAmount)||!expanded&&hoverAmount>.2&&hintBounds().contains(x,y);}
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            if(hoverAmount>.01&&!expanded){
                Rectangle hint=hintBounds();Graphics2D bubbleGraphics=(Graphics2D)g.create();
                double scale=1+.10*hoverAmount;
                bubbleGraphics.setComposite(AlphaComposite.SrcOver.derive(hoverAmount));
                bubbleGraphics.translate(hint.x,hint.y);bubbleGraphics.scale(scale,scale);
                Shape bubble=new RoundRectangle2D.Double(.1,.1,131.8,33.8,18,18);
                bubbleGraphics.setColor(Color.WHITE);bubbleGraphics.fill(bubble);
                bubbleGraphics.setStroke(new BasicStroke((float)(.2/scale)));bubbleGraphics.setColor(Color.BLACK);bubbleGraphics.draw(bubble);
                bubbleGraphics.setColor(INK);bubbleGraphics.setFont(LibraryDesign.medium(12));FontMetrics metrics=bubbleGraphics.getFontMetrics();
                bubbleGraphics.drawString("도와드릴까요?",(132-metrics.stringWidth("도와드릴까요?"))/2,(34-metrics.getHeight())/2+metrics.getAscent());bubbleGraphics.dispose();
            }
            AssistantAvatar.paint(g,178+ORB_HINT_PADDING,40,48+30d*hoverAmount);g.dispose();
        }
    }
    private static final class SparkIcon implements Icon{
        private final int size;private final Color color;SparkIcon(int size){this(size,INK);}SparkIcon(int size,Color color){this.size=size;this.color=color;}
        public int getIconWidth(){return size;}public int getIconHeight(){return size;}
        public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=(Graphics2D)graphics.create();g.translate(x,y);g.scale(size/20d,size/20d);g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(color);g.setStroke(new BasicStroke(1.4f));Path2D star=new Path2D.Float();star.moveTo(8,3);star.lineTo(10,8);star.lineTo(15,10);star.lineTo(10,12);star.lineTo(8,17);star.lineTo(6,12);star.lineTo(1,10);star.lineTo(6,8);star.closePath();g.draw(star);Path2D small=new Path2D.Float();small.moveTo(16,1);small.lineTo(17,3);small.lineTo(19,4);small.lineTo(17,5);small.lineTo(16,7);small.lineTo(15,5);small.lineTo(13,4);small.lineTo(15,3);small.closePath();g.draw(small);g.dispose();}
    }
    private static final class AssistantButton extends JButton {
        AssistantButton(String text){super(text);}
        @Override protected void paintComponent(Graphics graphics){
            Object painter=getClientProperty("synesis.assistantButtonPainter");
            if(painter instanceof javax.swing.plaf.ButtonUI ui)ui.paint(graphics,this);
            else super.paintComponent(graphics);
        }
    }
    private static void styleButton(JButton button,boolean primary){
        button.putClientProperty("synesis.preserveButton",true);
        button.putClientProperty("synesis.preserveFont",true);
        button.setBackground(BUTTON_BACKGROUND);button.setRolloverEnabled(true);
        button.setOpaque(false);button.setContentAreaFilled(false);button.setFocusPainted(false);button.setBorderPainted(false);
        button.setForeground(AssistantChatTheme.TEXT);button.setFont(LibraryDesign.medium(12));button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        button.setBorder(BorderFactory.createEmptyBorder(5,8,5,8));
        button.setUI(new javax.swing.plaf.basic.BasicButtonUI(){
            @Override public void paint(Graphics graphics,JComponent component){
                Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                Color fill=primary?(button.isEnabled()?new Color(0x5479ba):new Color(0x414a5a))
                    :button.getModel().isPressed()?new Color(0x292f39):button.getModel().isRollover()?new Color(0x414b5b):BUTTON_BACKGROUND;
                g.setColor(fill);g.fillRoundRect(0,0,component.getWidth(),component.getHeight(),12,12);g.dispose();super.paint(graphics,component);
            }
            @Override protected void paintText(Graphics g,AbstractButton b,Rectangle bounds,String text){
                g.setColor(b.isEnabled()?AssistantChatTheme.TEXT:AssistantChatTheme.MUTED);
                g.setFont(b.getFont());g.drawString(text,bounds.x,bounds.y+g.getFontMetrics().getAscent());
            }
        });
        button.putClientProperty("synesis.assistantButtonPainter",button.getUI());
    }
    private static final class MessageColumn extends JPanel implements Scrollable{
        MessageColumn(){setBorder(BorderFactory.createEmptyBorder(12,2,8,2));}
        public Dimension getPreferredScrollableViewportSize(){return getPreferredSize();}
        public int getScrollableUnitIncrement(Rectangle r,int o,int d){return 18;}
        public int getScrollableBlockIncrement(Rectangle r,int o,int d){return Math.max(36,r.height-36);}
        public boolean getScrollableTracksViewportWidth(){return true;}
        public boolean getScrollableTracksViewportHeight(){return false;}
    }
    /** Mentor-style waiting text, painted locally without rebuilding chat HTML. */
    private static final class ThinkingLabel extends JComponent{
        ThinkingLabel(){setPreferredSize(new Dimension(200,90));}
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            g.setFont(LibraryDesign.medium(15));float width=Math.max(1,getWidth());
            float phase=(System.nanoTime()%2_400_000_000L)/2_400_000_000f;float x=phase*width*2-width;
            g.setPaint(new LinearGradientPaint(x,0,x+width,0,new float[]{0,.5f,1},new Color[]{new Color(0x7E8A9D),new Color(0xD4E2F4),new Color(0x7E8A9D)},MultipleGradientPaint.CycleMethod.REPEAT));
            g.drawString("비서가",0,36);g.drawString("생각중이에요…",0,60);g.dispose();
        }
    }
    private final class ChatBubble extends JPanel{
        private final JTextPane live=new JTextPane();private final boolean user;
        private final ThinkingLabel thinking=new ThinkingLabel();
        private final JLabel sender=new JLabel("Synesis",new SparkIcon(15,AssistantChatTheme.TEXT),SwingConstants.LEFT);
        private final JPanel surface;
        private final JLabel cost=new JLabel(),time=new JLabel();private long answeredAt;
        private final MessageCopyButton copy;
        void metadata(String value,long at){answeredAt=at;cost.setText(value);time.setText(TutorPresentation.timeLabel(at,System.currentTimeMillis()));for(JLabel label:new JLabel[]{cost,time}){label.setForeground(AssistantChatTheme.MUTED);label.setFont(LibraryDesign.medium(10));if(label.getParent()==null)add(label);}revalidate();repaint();}
        private final long born=System.nanoTime();private float opacity;
        private String shown="";private boolean waiting,awaitingServer;
        private final AssistantActivityLog activity=new AssistantActivityLog();
        private String activityText="";
        private String answerText="";
        private boolean workPending;
        private String withActivity(String answer,boolean streaming){
            if(activityText.isEmpty())return answer;
            String remaining=activity.remainingAnswer(answer,streaming);
            return remaining.isBlank()?activityText:activityText+"\n\n"+remaining;
        }
        private boolean acceptActivity(JsonObject update){
            JsonObject accepted=activity.accept(update);if(accepted==null)return false;
            if(!activityText.isEmpty())activityText+="\n\n";
            activityText+=accepted.get("text").getAsString();return true;
        }
        void restoreActivity(JsonArray updates){for(JsonElement row:updates)acceptActivity(row.getAsJsonObject());}
        void addActivity(JsonObject update,boolean ongoing){
            if(!acceptActivity(update))return;
            workPending=ongoing;shown=withActivity(answerText,ongoing);copy.setEnabled(!shown.isBlank());
            renderAnswer(true);
        }
        void stopThinking(){workPending=false;waiting=false;renderAnswer(false);}
        private long arrivalStarted;
        private int arrivalScrollFrom;
        private int arrivalScrollMode;
        private boolean arrivalOwnsScrollMode;
        private java.awt.image.BufferedImage arrivalSnapshot;
        private void releaseArrival(){
            if(arrivalSnapshot!=null){arrivalSnapshot.flush();arrivalSnapshot=null;}
            if(arrivalOwnsScrollMode){if(enteringUser==null)scroll.getViewport().setScrollMode(arrivalScrollMode);arrivalOwnsScrollMode=false;}
        }
        void paintArrival(Graphics graphics){
            if(arrivalStarted==0)return;
            if(arrivalSnapshot==null){
                long started=arrivalStarted;arrivalStarted=0;Dimension size=getPreferredSize();arrivalStarted=started;
                if(size.width<=0||size.height<=0||(long)size.width*size.height>262144){arrivalStarted=0;releaseArrival();revalidate();scrollBottom();return;}
                Dimension previous=getSize();setSize(size);layoutArrival(this);
                arrivalSnapshot=new java.awt.image.BufferedImage(size.width,size.height,java.awt.image.BufferedImage.TYPE_INT_ARGB_PRE);
                Graphics2D cache=arrivalSnapshot.createGraphics();
                try{paintingEntrance=true;printAll(cache);}finally{paintingEntrance=false;cache.dispose();setSize(previous);layoutArrival(this);}
            }
            double t=Math.max(0,Math.min(1,(System.nanoTime()-arrivalStarted-80_000_000L)/520_000_000d));
            double scale=.16+.84*sendSpring(t/.78),rise=1-Math.pow(1-t,3);
            Point at=SwingUtilities.convertPoint(this,0,0,card);
            Graphics2D g=(Graphics2D)graphics.create();
            try{
                Rectangle viewport=SwingUtilities.convertRectangle(scroll.getViewport().getParent(),scroll.getViewport().getBounds(),card);g.clip(viewport);
                g.translate(at.x+arrivalSnapshot.getWidth()*(1-scale)/2,at.y+getHeight()-arrivalSnapshot.getHeight()*scale+28*(1-rise));
                g.scale(scale,scale);g.setComposite(AlphaComposite.SrcOver.derive((float)entranceEase(t/.18)));
                g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
                g.drawImage(arrivalSnapshot,0,0,null);
            }finally{g.dispose();}
        }
        private void layoutArrival(Container container){container.doLayout();for(Component child:container.getComponents())if(child instanceof Container nested)layoutArrival(nested);}

        private Component gapAfter;
        void serverArrived(){serverArrived(true);}
        void serverArrived(boolean animate){
            if(!awaitingServer)return;
            arrivalScrollFrom=scroll.getVerticalScrollBar().getValue();
            awaitingServer=false;setVisible(true);if(gapAfter!=null)gapAfter.setVisible(true);
            if(animate&&expanded&&HomeAssistant.this.isShowing()&&!Boolean.getBoolean("synesis.reduceMotion")){
                arrivalScrollMode=enteringUser==null?scroll.getViewport().getScrollMode():entranceScrollMode;
                arrivalOwnsScrollMode=true;scroll.getViewport().setScrollMode(JViewport.SIMPLE_SCROLL_MODE);
                arrivalStarted=System.nanoTime();motion.setDelay(16);
            }
            messages.revalidate();if(arrivalStarted==0)scrollBottom();repaint();
        }
        private PdfWorkspace.RoundedTutorBubble renderedAnswer;
        private JPanel imageStrip;
        private final AssistantDelivery.StatusLabel delivery=new AssistantDelivery.StatusLabel();private long receivedAt;
        void received(long at){received(at,false);}
        void received(long at,boolean uploaded){
            receivedAt=at;
            delivery.showStatus(AssistantDelivery.label(at,System.currentTimeMillis()));
            delivery.setToolTipText(uploaded?"요청 본문을 서버로 전송하면 표시해요":"이 메시지의 읽음 기록이에요");
        }

        private final TutorStreamFade streamFade=new TutorStreamFade(AssistantChatTheme.SURFACE.getRGB(),AssistantChatTheme.TEXT.getRGB(),680,true);
        private String markdownSource="",markdownHtml="";
        private int markdownWidth=-1;
        private long lastMarkdownPaint;
        private long nextMetadataUpdate;
        void advanceFade(){
            long now=System.currentTimeMillis();
            boolean thinking=renderedAnswer!=null&&workPending;
            if(arrivalStarted==0&&opacity>=1&&!delivery.animating()
                    &&(renderedAnswer==null||!renderedAnswer.animatingSize())&&!thinking
                    &&now<nextMetadataUpdate)return;
            if(arrivalStarted>0){
                long elapsed=System.nanoTime()-arrivalStarted;
                JScrollBar bar=scroll.getVerticalScrollBar();
                int target=Math.max(bar.getMinimum(),bar.getMaximum()-bar.getVisibleAmount());
                double glide=entranceEase(elapsed/260_000_000d);
                if(!bar.getValueIsAdjusting())bar.setValue((int)Math.round(arrivalScrollFrom+(target-arrivalScrollFrom)*glide));
                if(elapsed>=600_000_000L){arrivalStarted=0;releaseArrival();if(enteringUser==null)motion.setDelay(33);}
                card.repaint(scroll.getBounds());
            }
            if(now>=nextMetadataUpdate){
                nextMetadataUpdate=now+1000;
                if(user)delivery.showStatus(AssistantDelivery.label(receivedAt,now));
                if(answeredAt>0)time.setText(TutorPresentation.timeLabel(answeredAt,now));
            }
            if(user)delivery.advance();
            if(renderedAnswer!=null){
                if(renderedAnswer.animatingSize()){
                    boolean follow=busy&&nearBottom();
                    if(renderedAnswer.animateSize(System.nanoTime())){revalidate();messages.revalidate();if(follow)scrollBottom();}
                }
                if(thinking)renderedAnswer.repaintAssistantThinking();
            }
            if(opacity<1){opacity=Math.min(1,(System.nanoTime()-born)/200_000_000f);repaint();}}
        @Override public void paint(Graphics graphics){
            if(awaitingServer||(this==enteringUser||arrivalStarted>0)&&!paintingEntrance)return;
            Graphics2D g=(Graphics2D)graphics.create();
            float alpha=paintingEntrance?1:opacity;
            
            if(!paintingEntrance)g.setComposite(AlphaComposite.SrcOver.derive(alpha));
            super.paint(g);g.dispose();
        }
        ChatBubble(String value,boolean user){
            this.user=user;setLayout(null);setOpaque(false);setAlignmentX(LEFT_ALIGNMENT);
            copy=new MessageCopyButton(user?"메시지 복사":"답변 복사",AssistantChatTheme.MUTED,()->shown,text->status.setText(text),.7f);
            copy.setEnabled(!value.isBlank());add(copy);
            surface=new JPanel(new BorderLayout()){
                @Override protected void paintComponent(Graphics graphics){if(renderedAnswer!=null)return;Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(user?AssistantChatTheme.USER:AssistantChatTheme.SURFACE);g.fillRoundRect(0,0,getWidth()-1,getHeight()-1,20,20);if(!user){g.setColor(AssistantChatTheme.LINE);g.drawRoundRect(0,0,getWidth()-1,getHeight()-1,20,20);}g.dispose();}
            };
            surface.setOpaque(false);surface.setBorder(BorderFactory.createEmptyBorder(13,14,13,14));
            live.setEditable(false);dev.synesis.poc.ui.ReadOnlyCaret.applyTo(live);live.setOpaque(false);live.setBorder(null);live.setForeground(AssistantChatTheme.TEXT);live.setFont(CHAT_FONT);live.setText(value);shown=value;
            answerText=value;
            ((javax.swing.text.DefaultCaret)live.getCaret()).setUpdatePolicy(javax.swing.text.DefaultCaret.NEVER_UPDATE);
            surface.add(live);add(surface);
            if(user){delivery.showStatus(AssistantDelivery.label(0,System.currentTimeMillis()));delivery.setFont(LibraryDesign.medium(10));delivery.setHorizontalAlignment(SwingConstants.RIGHT);add(delivery);}
            sender.setFont(LibraryDesign.medium(11));sender.setForeground(AssistantChatTheme.TEXT);
            if(!user){add(sender);}
        }
        void addImages(java.util.List<AssistantAttachments.Item> images){
            imageStrip=AssistantAttachments.bubble(images);
            JPanel content=new JPanel(new BorderLayout());content.setOpaque(false);content.add(imageStrip,BorderLayout.NORTH);content.add(live);surface.removeAll();surface.add(content);
        }
        void thinking(){metadata("크레딧 계산중",System.currentTimeMillis());copy.setEnabled(false);waiting=true;workPending=true;renderAnswer(false);renderedAnswer.prepareAssistantThinking();revalidate();repaint();}
        void stream(String value){
            boolean first=waiting;waiting=false;
            answerText=value;String combined=withActivity(value,true);
            if(!combined.startsWith(shown))streamFade.reset();
            shown=combined;
            copy.setEnabled(!shown.isBlank());
            // Coalesce reveals and fade frames; the mentor renderer retains unchanged panes.
            if(first||renderedAnswer==null||System.nanoTime()-lastMarkdownPaint>=40_000_000L)renderAnswer(true);
        }
        void animateText(){
            if(waiting&&activityText.isEmpty())return;
            if(System.nanoTime()-lastMarkdownPaint>=40_000_000L&&(!shown.equals(markdownSource)||streamFade.active(System.currentTimeMillis())))renderAnswer(true);
        }
        void finish(String value){
            if(awaitingServer)serverArrived();waiting=false;workPending=false;answerText=value;shown=withActivity(value,false);copy.setEnabled(!shown.isBlank());renderAnswer(false);
        }
        private void renderAnswer(boolean streaming){
            int width=bubbleWidth();boolean widthChanged=width!=markdownWidth;long now=System.currentTimeMillis();
            boolean changed=!shown.equals(markdownSource)||width!=markdownWidth;
            if(!shown.equals(markdownSource)||width!=markdownWidth){
                markdownHtml=AssistantSources.render(shown,CHAT_FONT.getSize(),Math.max(80,width-32));
                markdownSource=shown;markdownWidth=width;if(streaming)streamFade.accept(markdownHtml,now);
            }
            if(!streaming)streamFade.reset();
            String content=streaming?streamFade.decorate(markdownHtml,now):markdownHtml;
            if(renderedAnswer==null){
                renderedAnswer=PdfWorkspace.assistantAnswerBubble(content,width,CHAT_FONT.getSize(),HomeAssistant.this::openAnswerLink);
                surface.removeAll();surface.setBorder(null);surface.add(renderedAnswer);
            }else renderedAnswer.updateContent(content,width,CHAT_FONT.getSize());
            if(widthChanged)renderedAnswer.reflowWidth(width);
            renderedAnswer.setThinking(workPending,workPending&&shown.isBlank());
            if(streaming&&changed)streamFade.readyToPaint(now,System.currentTimeMillis());
            lastMarkdownPaint=System.nanoTime();revalidate();repaint();
        }
        private int columnWidth(){return Math.max(160,scroll.getViewport().getWidth()-4);}
        private int bubbleWidth(){return user?(int)(columnWidth()*.84):columnWidth();}
        @Override public Dimension getPreferredSize(){
            if(renderedAnswer!=null&&markdownWidth!=bubbleWidth())renderAnswer(false);
            int w=bubbleWidth();Component content=surface.getComponent(0);
            // The animated renderer owns its height. Stretching it to MAX_VALUE here
            // invalidates its entire HTML tree on every BoxLayout measurement.
            if(renderedAnswer==null&&live.getWidth()!=Math.max(1,w-28))live.setSize(Math.max(1,w-28),Short.MAX_VALUE);
            if(imageStrip!=null){GridLayout grid=(GridLayout)imageStrip.getLayout();int columns=Math.max(1,Math.min(3,(w-28)/87));if(grid.getColumns()!=columns)grid.setColumns(columns);}
            int h=renderedAnswer==null?live.getPreferredSize().height+26+(imageStrip==null?0:imageStrip.getPreferredSize().height):content.getPreferredSize().height;
            int total=h+(user?24:answeredAt>0?58:30);
            return new Dimension(columnWidth(),total);
        }
        @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
        @Override public void doLayout(){int width=user?(int)(getWidth()*.84):getWidth();int y=user?0:26;
            surface.setBounds(user?getWidth()-width:0,y,width,Math.max(1,getHeight()-y-(user?24:answeredAt>0?32:4)));
            int copySize=copy.getPreferredSize().width;
            copy.setBounds(user?getWidth()-copySize:0,getHeight()-22+(20-copySize)/2,copySize,copySize);
            if(answeredAt>0){int costWidth=cost.getPreferredSize().width;cost.setBounds(copySize+6,getHeight()-24,costWidth,20);time.setHorizontalAlignment(SwingConstants.RIGHT);time.setBounds(copySize+10+costWidth,getHeight()-24,Math.max(1,getWidth()-copySize-12-costWidth),20);}
            if(user)delivery.setBounds(getWidth()-width,getHeight()-22,Math.max(1,width-copySize-4),20);
            if(!user){sender.setBounds(0,0,getWidth(),22);}
        }
    }
}
