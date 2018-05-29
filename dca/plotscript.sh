#!/bin/bash
# Comment out to avoid running
runsim=""
# runplot=""

# Whether to run non-VNets or not
nonvnets=""

# targs=""
# grads=""
# hla=""
final=""

# events=100000
events=470000

# logiter=5000
logiter=25000

avg=16
ext=".4"

sarsa_dir="sarsas/"
fixed_dir="fixed/"
vnet_dir=""  # Only used for loading files when plotting, not when saving


runargs=(--log_iter "${logiter}"
         --log_level 30
         --avg_runs "${avg}"
         -i "${events}"
         --log_file "plots/plot-log${ext}"
         -epol greedy
         --breakout_thresh 0.4)

## TARGETS ##
if [ -v targs ]; then
    if [ -v runsim ]; then
        # # SMDP Discount
        python3 main.py singhnet "${runargs[@]}" \
                -save_bp semi-smdp-hoff --target discount -rtype smdp_callcount \
                -phoff --beta_disc --beta 21 -lr 5.1e-6 || exit 1
        # # MDP Discount
        python3 main.py singhnet "${runargs[@]}" \
                -phoff -save_bp semi-mdp-hoff --target discount \
                --net_lr 2.02e-7 || exit 1
        # MDP Average
        python3 main.py singhnet "${runargs[@]}" \
                -phoff -save_bp semi-avg-hoff \
                --net_lr 3.43e-06 --weight_beta 0.00368 || exit 1
    fi
    if [ -v runplot ]; then
        python3 plotter.py "${vnet_dir}semi-smdp-hoff" "${vnet_dir}semi-mdp-hoff" "${vnet_dir}semi-avg-hoff" \
                --labels "SMDP discount [SB-VNet]" "MDP discount" "MDP avg. rewards" \
                --title "Target comparison (with hand-offs)" \
                --ext $ext --ctype new hoff tot --plot_save targets --ymins 10 5 10 || exit 1
    fi
    echo "Finished targets"
fi

if [ -v grads ]; then
    ## GRADIENTS (no hoffs) ##
    if [ -v runsim ]; then
        # Semi-grad A-MDP (same as "MDP Average", without hoffs)
        python3 main.py singhnet "${runargs[@]}" \
                -save_bp semi-avg  --net_lr 3.43e-06 --weight_beta 0.00368 || exit 1
        # Residual grad A-MDP
        python3 main.py residsinghnet "${runargs[@]}" \
                -save_bp resid-avg --net_lr 1.6e-05 || exit 1
        #  TDC A-MDP
        python3 main.py tftdcsinghnet "${runargs[@]}" \
                -save_bp tdc-avg || exit 1
        # #  TDC MDP Discount
        python3 main.py tftdcsinghnet "${runargs[@]}" \
                -save_bp tdc-mdp --target discount \
                --net_lr 1.91e-06 --grad_beta 5e-09 || exit 1
    fi
    if [ -v runplot ]; then
        python3 plotter.py "${vnet_dir}semi-avg" "${vnet_dir}resid-avg" \
                "${vnet_dir}tdc-avg" "${vnet_dir}tdc-mdp" \
                --labels "Semi-grad. (A-MDP)" "Residual grad. (A-MDP)" \
                "TDC (A-MDP) [AA-VNet]" "TDC (MDP)" \
                --title "Gradient comparison (no hand-offs)" \
                --ext $ext --ctype new --plot_save grads --ymins 5 || exit 1
    fi
    echo "Finished Grads"
fi

## Exploration RS-SARSA ##
# if [ -v runsim ]; then
#     # RS-SARSA 
#     python3 main.py rs_sarsa --log_iter $logiter --avg_runs $avg $runt \
#             -save_bp rssarsa-hla-hoff --target discount -phoff 0.15 -hla || exit 1
# fi
# python3 plotter.py "exp-rssarsa-greedy" "exp-rssarsa-boltzlo" "exp-rssarsa-boltzhi" \
#         --labels "RS-SARSA Greedy" "RS-SARSA Boltmann Low" "RS-SARSA Boltmann High" \
#         --title "Exploration for state-action methods" \
#         --ctype new hoff --plot_save exp-rssarsa || exit 1

## Exploration VNet ##
# if [ -v runsim ]; then
#     # VNet greedy
#     python3 main.py rs_sarsa --log_iter $logiter --avg_runs $avg $runt \
#             -save_bp exp-vnet-greedy --target discount -phoff 0.15 -hla || exit 1
# fi
# python3 plotter.py "exp-vnet-greedy" "exp-vnet-boltzlo" "exp-vnet-boltzhi" \
#         --labels "VNet Greedy" "VNet Boltmann Low" "VNet Boltmann High" \
#         --title "Exploration for state methods" \
#         --ext $ext --ctype new hoff --plot_save exp-vnet || exit 1

if [ -v hla ]; then
    ## HLA ##
    if [ -v runsim ]; then
        if [ -v nonvnets ]; then
            # # RS-SARSA
            python3 main.py rs_sarsa "${runargs[@]}" \
                    -save_bp "${sarsa_dir}rssarsa-hoff" --lilith -phoff || exit 1
            # # RS-SARSA HLA
            python3 main.py hla_rs_sarsa "${runargs[@]}" \
                    -save_bp "${sarsa_dir}rssarsa-hla-hoff" --lilith -phoff -hla || exit 1
        fi
        #  TDC A-MDP
        python3 main.py tftdcsinghnet "${runargs[@]}" \
                -save_bp tdc-avg-hoff -phoff || exit 1
        # TDC A-MDP HLA
        python3 main.py tftdcsinghnet "${runargs[@]}" \
                -save_bp tdc-avg-hla-hoff -hla -phoff || exit 1
    fi
    if [ -v runplot ]; then
        python3 plotter.py "${vnet_dir}tdc-avg-hoff" "${vnet_dir}tdc-avg-hla-hoff" \
                "${sarsa_dir}rssarsa-hoff" "${sarsa_dir}rssarsa-hla-hoff" \
                --labels "TDC (A-MDP)" "TDC (A-MDP) (HLA) [AA-VNet]" "RS-SARSA" "RS-SARSA (HLA)" \
                --title "Hand-off look-ahead" \
                --ext $ext --ctype new hoff tot --plot_save hla --ymins 10 0 10 || exit 1
    fi
    echo "Finished HLA"
fi

if [ -v final ]; then
    ## Final comparison, without hoffs
    if [ -v runsim ]; then
        for i in {5..10}
        do
            if [ -v nonvnets ] ; then
                # # FCA
                # python3 main.py fixedassign "${runargs[@]}" \
                #         -save_bp "fca-e${i}" --erlangs $i || exit 1
                # FCA
                python3 main.py fixedassign "${runargs[@]}" \
                        -save_bp "${fixed_dir}fca-hoff-e${i}" -phoff --erlangs $i || exit 1

                # # RandomAssign
                # python3 main.py randomassign "${runargs[@]}" \
                #         -save_bp "rand-e${i}" --erlangs $i  || exit 1
                # RandomAssign
                python3 main.py randomassign "${runargs[@]}" \
                        -save_bp "${fixed_dir}rand-hoff-e${i}" -phoff --erlangs $i  || exit 1

                # # RS-SARSA
                # python3 main.py rs_sarsa "${runargs[@]}" \
                #         -save_bp "rssarsa-e${i}" --lilith --erlangs $i || exit 1

            fi
            # # TDC avg.
            # python3 main.py tftdcsinghnet "${runargs[@]}" \
            #         -save_bp "tdc-avg-e${i}" --erlangs $i || exit 1
        done
        # Erlangs = 10 already done in HLA section
        for i in {5..9}
        do
            if [ -v nonvnets ] ; then
                # RS-SARSA HLA
                python3 main.py hla_rs_sarsa "${runargs[@]}" \
                        -save_bp "${sarsa_dir}rssarsa-hla-hoff-e${i}" --lilith -phoff -hla || exit 1

            fi
            # TDC A-MDP HLA
            python3 main.py tftdcsinghnet "${runargs[@]}" \
                    -save_bp "tdc-avg-hla-hoff-e${i}" -hla -phoff --erlangs $i || exit 1
       done
    fi
    if [ -v runplot ]; then
        # python3 plotter.py "${vnet_dir}tdc-avg" "${sarsa_dir}rssarsa" \
        #         "${fixed_dir}fca" "${fixed_dir}rand" \
        #         --labels "AA-VNet" "RS-SARSA" "FCA" "Random assignment" \
        #         --title "RL vs non-learning agents (no hand-offs)" \
        #         --erlangs --ext $ext --ctype new --plot_save final-nohoff --ymins 10 || exit 1
        python3 plotter.py "${vnet_dir}tdc-avg-hla-hoff" "${sarsa_dir}rssarsa-hla-hoff" \
                "${fixed_dir}final-fca" "${fixed_dir}final-rand" \
                --labels "TDC (A-MDP) (HLA) [AA-VNet]" "RS-SARSA (HLA)" "FCA" "Random assignment" \
                --title "RL vs non-learning agents (with hand-offs)" \
                --erlangs --ext $ext --ctype new hoff tot --plot_save final --ymins 10 0 10 || exit 1
    fi
    echo "Finished Final"
fi
echo "FINISHED ALL"
