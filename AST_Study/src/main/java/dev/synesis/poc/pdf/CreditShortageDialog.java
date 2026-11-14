package dev.synesis.poc.pdf;

import javax.swing.*;
import java.awt.Component;
import java.nio.file.Path;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Shared shortage action for imports, generation and partial results. */
final class CreditShortageDialog {
    private static final ExecutorService WORKER=Executors.newSingleThreadExecutor(job->{
        Thread thread=new Thread(job,"credit-shortage-checkout");thread.setDaemon(true);return thread;
    });
    static void show(Component parent,String message) {
        int answer=JOptionPane.showOptionDialog(parent,message,"크레딧 부족",
            JOptionPane.DEFAULT_OPTION,JOptionPane.WARNING_MESSAGE,null,
            new String[]{"플랜 업그레이드 하러 가기","닫기"},"플랜 업그레이드 하러 가기");
        if(answer!=0)return;
        Path root=PdfLibraryStore.defaultRoot();
        WORKER.execute(()->{
            try {
                SubscriptionUsage.activate(root);
                var totals=PdfUsageStore.read(root,PdfLibraryStore.list(root));
                var wallet=CreditWallet.read(root,totals.usd());
                SwingUtilities.invokeLater(()->CreditTopUpDialog.open(parent,root,wallet,WORKER,()->{}));
            } catch(Exception error) {
                SwingUtilities.invokeLater(()->JOptionPane.showMessageDialog(parent,
                    "결제창을 열지 못했어요. 내 정보의 충전하기에서 다시 시도해 주세요.","결제창",JOptionPane.WARNING_MESSAGE));
            }
        });
    }
}
