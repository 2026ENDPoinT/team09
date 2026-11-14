package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.StudyTheme;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.Path;
import java.util.Locale;
import java.util.concurrent.ExecutorService;

/** Developer-only simulated checkout. No provider SDK, card collection, or network calls. */
final class CreditTopUpDialog {
    static final BigDecimal RETAIL_KRW = new BigDecimal("4");

    static void open(Component parent,Path root,CreditWallet.Snapshot wallet,
                     ExecutorService worker,Runnable updated) {
        if(wallet==null)return;
        JDialog dialog=new JDialog(parent==null?null:SwingUtilities.getWindowAncestor(parent),"크레딧 충전",Dialog.ModalityType.APPLICATION_MODAL);
        JPanel body=new JPanel(new BorderLayout(0,22));body.setBackground(StudyTheme.CANVAS);
        body.setBorder(new EmptyBorder(26,28,26,28));
        JPanel header=column();
        header.add(label("나에게 맞는 크레딧을 골라보세요",23,Font.BOLD,StudyTheme.INK));
        header.add(Box.createVerticalStrut(10));
        header.add(label("개발자 모드 · 실제 금액은 청구되지 않아요",12,Font.PLAIN,StudyTheme.ACCENT));
        body.add(header,BorderLayout.NORTH);

        JTabbedPane tabs=new JTabbedPane();tabs.setFont(StudyTheme.font(Font.PLAIN,13));
        JPanel plans=new JPanel(new GridLayout(1,3,12,0));plans.setOpaque(false);
        plans.setBorder(new EmptyBorder(18,4,18,4));
        ButtonGroup group=new ButtonGroup();
        JRadioButton[] choices=new JRadioButton[CreditWallet.PLANS.length];
        for(int i=0;i<choices.length;i++) {
            CreditWallet.Plan plan=CreditWallet.PLANS[i];
            JPanel card=StudyTheme.panel(14,StudyTheme.PAPER);
            card.setLayout(new BoxLayout(card,BoxLayout.Y_AXIS));
            card.setBorder(new EmptyBorder(20,16,20,16));
            choices[i]=new JRadioButton(plan.name());choices[i].setOpaque(false);
            choices[i].setFont(StudyTheme.font(Font.BOLD,17));choices[i].setForeground(StudyTheme.INK);
            choices[i].setAlignmentX(Component.LEFT_ALIGNMENT);group.add(choices[i]);card.add(choices[i]);
            card.add(Box.createVerticalStrut(22));
            card.add(label(String.format(Locale.KOREA,"%,d원",plan.won()),25,Font.BOLD,StudyTheme.INK));
            card.add(Box.createVerticalStrut(10));
            card.add(label(String.format(Locale.KOREA,"%,d 크레딧",plan.credits()),17,Font.BOLD,StudyTheme.ACCENT));
            card.add(Box.createVerticalStrut(20));
            double discount=(1-plan.won()/(plan.credits()*RETAIL_KRW.doubleValue()))*100;
            card.add(label(discount>0?String.format(Locale.KOREA,"별도 구매 대비 %.1f%% 할인",discount):"별도 구매 대비 할인 없음",
                12,Font.BOLD,StudyTheme.ACCENT));
            if(discount<0) {
                card.add(Box.createVerticalStrut(6));
                card.add(label(String.format(Locale.KOREA,"크레딧당 가격 %.1f%% 높음",-discount),11,Font.PLAIN,StudyTheme.MUTED));
            }
            card.add(Box.createVerticalStrut(12));
            card.add(label(String.format(Locale.KOREA,"1크레딧 = %.2f원",plan.won()/(double)plan.credits()),12,Font.PLAIN,StudyTheme.MUTED));
            card.add(Box.createVerticalStrut(12));
            card.add(label("30일마다 자동결제 예정 (모의)",11,Font.PLAIN,StudyTheme.MUTED));
            plans.add(card);
        }
        choices[0].setSelected(true);
        tabs.addTab("플랜 선택",plans);

        JPanel custom=column();custom.setBorder(new EmptyBorder(25,22,25,22));
        boolean member=wallet.hasActivePlan();
        int minimum=member?0:1000;
        custom.add(label("필요한 만큼 크레딧 구매",21,Font.BOLD,StudyTheme.INK));
        custom.add(Box.createVerticalStrut(14));
        custom.add(label("1크레딧 = 4원",17,Font.BOLD,StudyTheme.ACCENT));
        custom.add(Box.createVerticalStrut(12));
        custom.add(label(member?wallet.activePlan()+" 이용 중 · 최소 구매 수량 제한 없음":"플랜 미이용 · 최소 1,000크레딧부터 구매 가능",
            12,Font.PLAIN,StudyTheme.MUTED));
        custom.add(Box.createVerticalStrut(20));
        JSpinner amount=new JSpinner(new SpinnerNumberModel(member?0:1000,minimum,1_000_000,1));
        amount.setEditor(new JSpinner.NumberEditor(amount,"#,##0"));
        amount.setFont(StudyTheme.font(Font.PLAIN,18));
        JPanel quantityRow=new JPanel(new BorderLayout(12,0));quantityRow.setOpaque(false);
        quantityRow.setAlignmentX(Component.LEFT_ALIGNMENT);
        quantityRow.setMaximumSize(new Dimension(440,42));
        quantityRow.setPreferredSize(new Dimension(440,42));
        JButton calculate=new JButton("계산하기");StudyTheme.button(calculate,false);
        quantityRow.add(amount,BorderLayout.CENTER);quantityRow.add(calculate,BorderLayout.EAST);
        custom.add(quantityRow);custom.add(Box.createVerticalStrut(16));
        JLabel customPrice=label("",20,Font.BOLD,StudyTheme.INK);custom.add(customPrice);
        custom.add(Box.createVerticalStrut(10));
        custom.add(label("크레딧은 누적 충전돼요. 0개는 결제할 수 없어요.",12,Font.PLAIN,StudyTheme.MUTED));
        custom.add(Box.createVerticalStrut(6));
        custom.add(label("결제 금액은 원 단위로 올림해요.",11,Font.PLAIN,StudyTheme.MUTED));
        tabs.addTab("크레딧 별도 구매",custom);
        body.add(tabs,BorderLayout.CENTER);

        JPanel footer=new JPanel(new BorderLayout(12,10));footer.setOpaque(false);
        JLabel order=label("",13,Font.PLAIN,StudyTheme.MUTED);footer.add(order,BorderLayout.CENTER);
        JButton pay=new JButton("결제하기");StudyTheme.button(pay,true);footer.add(pay,BorderLayout.EAST);
        body.add(footer,BorderLayout.SOUTH);
        Runnable quote=()->{
            int count=((Number)amount.getValue()).intValue();
            BigDecimal won=RETAIL_KRW.multiply(BigDecimal.valueOf(count));
            customPrice.setText(String.format(Locale.KOREA,"결제 금액 %,.0f원",won.setScale(0,RoundingMode.CEILING)));
            if(tabs.getSelectedIndex()==1) {
                order.setText(String.format(Locale.KOREA,"%,d 크레딧 · %,.0f원",count,won.setScale(0,RoundingMode.CEILING)));
                pay.setEnabled(count>0);
            } else {
                for(int i=0;i<choices.length;i++)if(choices[i].isSelected()) {
                    CreditWallet.Plan plan=CreditWallet.PLANS[i];
                    order.setText(String.format(Locale.KOREA,"%s · %,d 크레딧 · %,d원",plan.name(),plan.credits(),plan.won()));
                }
                pay.setEnabled(true);
            }
        };
        tabs.addChangeListener(event->quote.run());amount.addChangeListener(event->quote.run());
        calculate.addActionListener(event->{
            try {amount.commitEdit();quote.run();}
            catch(java.text.ParseException failure) {
                JOptionPane.showMessageDialog(dialog,"구매 수량을 숫자로 입력해 주세요.");
            }
        });
        for(JRadioButton choice:choices)choice.addActionListener(event->quote.run());
        quote.run();
        pay.addActionListener(event->{
            try {amount.commitEdit();}catch(java.text.ParseException failure) {
                JOptionPane.showMessageDialog(dialog,"구매 수량을 숫자로 입력해 주세요.");return;
            }
            boolean standalone=tabs.getSelectedIndex()==1;
            int count=((Number)amount.getValue()).intValue();
            CreditWallet.Plan selected=null;
            for(int i=0;i<choices.length;i++)if(choices[i].isSelected())selected=CreditWallet.PLANS[i];
            CreditWallet.Plan plan=selected;
            pay.setEnabled(false);tabs.setEnabled(false);amount.setEnabled(false);calculate.setEnabled(false);
            for(JRadioButton choice:choices)choice.setEnabled(false);
            pay.setText("처리 중…");dialog.setDefaultCloseOperation(WindowConstants.DO_NOTHING_ON_CLOSE);
            worker.execute(()->{
                try {
                    CreditWallet.Snapshot result=standalone?CreditWallet.purchaseCredits(root,count,RETAIL_KRW):CreditWallet.topUp(root,plan);
                    SwingUtilities.invokeLater(()->{
                        updated.run();
                        JPanel success=column();success.setBorder(new EmptyBorder(45,45,45,45));
                        success.add(label("결제 성공",28,Font.BOLD,StudyTheme.ACCENT));
                        success.add(Box.createVerticalStrut(20));
                        success.add(label(String.format(Locale.KOREA,"%,d 크레딧이 충전됐어요.",standalone?count:plan.credits()),19,Font.BOLD,StudyTheme.INK));
                        success.add(Box.createVerticalStrut(14));
                        success.add(label(CreditWallet.displayHtml(result.balance(),17).replace("<html>","<html>잔여 "),17,Font.PLAIN,StudyTheme.INK));
                        success.add(Box.createVerticalStrut(18));
                        success.add(label("개발자 모드 모의 결제 · 실제 결제 없음",12,Font.PLAIN,StudyTheme.MUTED));
                        success.add(Box.createVerticalStrut(30));
                        JButton done=new JButton("내 정보로");StudyTheme.button(done,true);
                        done.setAlignmentX(Component.LEFT_ALIGNMENT);done.addActionListener(e->dialog.dispose());success.add(done);
                        dialog.setContentPane(success);dialog.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
                        dialog.getRootPane().setDefaultButton(done);dialog.revalidate();dialog.repaint();
                    });
                } catch(Exception failure) {
                    SwingUtilities.invokeLater(()->{
                        tabs.setEnabled(true);amount.setEnabled(true);calculate.setEnabled(true);for(JRadioButton choice:choices)choice.setEnabled(true);
                        pay.setText("결제하기");quote.run();dialog.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
                        JOptionPane.showMessageDialog(dialog,"충전하지 못했어요.\n"+failure.getMessage(),"충전 실패",JOptionPane.ERROR_MESSAGE);
                    });
                }
            });
        });
        dialog.setContentPane(body);dialog.setSize(820,530);dialog.setMinimumSize(new Dimension(780,500));
        dialog.setLocationRelativeTo(parent);dialog.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        dialog.setVisible(true);
    }

    private static JPanel column() {
        JPanel panel=new JPanel();panel.setBackground(StudyTheme.CANVAS);
        panel.setLayout(new BoxLayout(panel,BoxLayout.Y_AXIS));return panel;
    }
    private static JLabel label(String text,int size,int style,Color color) {
        JLabel label=new JLabel(text);label.setFont(StudyTheme.font(style,size));label.setForeground(color);
        label.setAlignmentX(Component.LEFT_ALIGNMENT);return label;
    }
}
